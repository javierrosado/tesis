# /// script
# requires-python = ">=3.11"
# dependencies = ["torch", "transformers>=4.51,<4.57", "peft>=0.13", "trl>=0.19,<0.24", "bitsandbytes", "datasets", "accelerate", "huggingface_hub"]
# ///
"""F3 · QLoRA de los agentes entrenables (uno por dominio) sobre Qwen3-8B.
Datos: SFT_REPO (prompt de inferencia → salida aprobada por governance). Pérdida solo sobre la salida (completion).
Cada adaptador se publica privado en el Hub como <usuario>/qwen3-8b-<agente>-lora.
Variables: SFT_REPO, AGENTS (coma), EPOCHS, LR, RANK, MAX_LEN, RUNS_REPO."""
import gc, json, os, time
import torch
from datasets import Dataset
from huggingface_hub import HfApi, hf_hub_download, whoami
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer
from importlib import metadata
print("ENTORNO", {p: metadata.version(p) for p in ("torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate", "datasets")}, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu", flush=True)

BASE = os.environ.get("BASE", "Qwen/Qwen3-8B"); SFT = os.environ["SFT_REPO"]
AGENTS = os.environ.get("AGENTS", "product-analyst-agent,solution-architect-agent,api-designer-agent,test-case-generator-agent,cicd-pipeline-agent").split(",")
EPOCHS = float(os.environ.get("EPOCHS", "2")); LR = float(os.environ.get("LR", "2e-4")); RANK = int(os.environ.get("RANK", "16"))
MAX_LEN = int(os.environ.get("MAX_LEN", "8192")); SEED = 2026
USER = whoami()["name"]; api = HfApi()
tok = AutoTokenizer.from_pretrained(BASE)


def load(agent, split):
    rows = [json.loads(l) for l in open(hf_hub_download(SFT, f"{agent}/{split}.jsonl", repo_type="dataset"), encoding="utf-8")]
    data, dropped = [], 0
    for r in rows:
        prompt = tok.apply_chat_template(r["messages"][:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        completion = r["messages"][-1]["content"] + "<|im_end|>\n"
        if len(tok(prompt + completion)["input_ids"]) > MAX_LEN:
            dropped += 1; continue
        data.append({"prompt": prompt, "completion": completion})
    return Dataset.from_list(data), dropped


summary = {"base": BASE, "sft_repo": SFT, "epochs": EPOCHS, "lr": LR, "rank": RANK, "max_len": MAX_LEN, "seed": SEED, "agentes": {}}
for agent in AGENTS:
    t0 = time.time()
    train, d_tr = load(agent, "train"); val, d_va = load(agent, "val")
    model = AutoModelForCausalLM.from_pretrained(BASE, device_map="auto", torch_dtype=torch.bfloat16, attn_implementation="sdpa",
                                                 quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                                                        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    cfg = SFTConfig(output_dir=f"/tmp/out/{agent}", num_train_epochs=EPOCHS, per_device_train_batch_size=1, gradient_accumulation_steps=8,
                    learning_rate=LR, lr_scheduler_type="cosine", warmup_ratio=0.05, bf16=True, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                    max_length=MAX_LEN, completion_only_loss=True, packing=False, eval_strategy="epoch", per_device_eval_batch_size=1,
                    logging_steps=5, save_strategy="no", report_to="none", seed=SEED, dataset_kwargs={"add_special_tokens": False})
    lora = LoraConfig(r=RANK, lora_alpha=2 * RANK, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    tr = SFTTrainer(model=model, args=cfg, train_dataset=train, eval_dataset=val, processing_class=tok, peft_config=lora)
    res = tr.train(); ev = tr.evaluate()
    repo = f"{USER}/qwen3-8b-{agent.removesuffix('-agent')}-lora"
    tr.save_model(f"/tmp/adapters/{agent}")
    api.create_repo(repo, private=True, exist_ok=True)
    api.upload_folder(folder_path=f"/tmp/adapters/{agent}", repo_id=repo, commit_message=f"QLoRA {agent} sobre {BASE}")
    losses = [h for h in tr.state.log_history if "loss" in h]
    summary["agentes"][agent] = {"repo": repo, "n_train": len(train), "n_val": len(val), "descartados_por_longitud": d_tr + d_va,
                                 "train_loss": res.training_loss, "eval_loss": ev.get("eval_loss"), "primera_loss": losses[0]["loss"] if losses else None,
                                 "ultima_loss": losses[-1]["loss"] if losses else None, "minutos": round((time.time() - t0) / 60, 1)}
    print("ADAPTADOR", json.dumps(summary["agentes"][agent]), flush=True)
    del tr, model; gc.collect(); torch.cuda.empty_cache()
    p = "/tmp/f3_train_resumen.json"; json.dump(summary, open(p, "w"), indent=1)
    api.upload_file(path_or_fileobj=p, path_in_repo=f"runs/f3_train/{os.environ.get('JOB_ID', 'local')}/resumen.json", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
print("FIN", json.dumps(summary, indent=1))
