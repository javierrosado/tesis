"""knowledge-rag-agent, versión mínima: índice léxico (BM25) sobre data/knowledge/.
Expone search(query, k) → fragmentos con id citable (BR-010, ADR-003, SPEC:openapi_pedidos_v1, POL:release, …).
La interfaz es estable; el motor (BM25, embeddings, vector store) es detalle de implementación y
puede cambiar sin tocar a los agentes."""
import math, re
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[a-záéíóúñü0-9\-]{2,}", re.I)


def _chunks(root: Path):
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in (".md", ".yaml", ".yml", ".txt"):
            continue
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8", errors="ignore")
        if rel.startswith("reglas_negocio"):          # una regla por fila → un chunk por BR-xxx
            for line in text.splitlines():
                m = re.match(r"\|\s*(BR-\d{3})\s*\|(.*)", line)
                if m:
                    yield {"id": m.group(1), "source": rel, "text": m.group(1) + " " + m.group(2).replace("|", " ").strip()}
        elif rel.startswith("adr"):
            yield {"id": f.stem, "source": rel, "text": text}
        elif rel.startswith("spec"):
            yield {"id": "SPEC:" + f.stem, "source": rel, "text": text[:6000]}
        elif rel.startswith("politicas"):
            yield {"id": "POL:" + f.stem.replace("politica_", ""), "source": rel, "text": text}
        elif rel.startswith("convenciones"):
            yield {"id": "CONV:" + f.stem, "source": rel, "text": text}
        elif f.name == "glosario.md":
            for line in text.splitlines():
                m = re.match(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
                if m and not m.group(1).lower().startswith(("término", "---", "termino")):
                    yield {"id": "GLOS:" + m.group(1), "source": rel, "text": m.group(1) + ": " + m.group(2)}


class KnowledgeRag:
    def __init__(self, root: Path, k1: float = 1.5, b: float = 0.75):
        self.docs = list(_chunks(Path(root)))
        self.k1, self.b = k1, b
        self.tf = [Counter(t.lower() for t in TOKEN.findall(d["text"])) for d in self.docs]
        self.dl = [sum(c.values()) for c in self.tf]
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 1
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = [t.lower() for t in TOKEN.findall(query)]
        scores = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t in c:
                    f = c[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl))
            # refuerzo por id exacto (BR-010, ADR-003)
            if self.docs[i]["id"].lower() in q or self.docs[i]["id"].lower() in query.lower():
                s += 10
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        return [{"id": self.docs[i]["id"], "source": self.docs[i]["source"], "score": round(s, 2),
                 "text": self.docs[i]["text"][:1200]} for s, i in scores[:k]]

    def context_block(self, queries: list[str], k: int = 4) -> tuple[str, list[str]]:
        """Devuelve texto listo para el prompt y la lista de ids usados (para provenance.knowledge_refs)."""
        seen, parts = {}, []
        for q in queries:
            for hit in self.search(q, k):
                if hit["id"] not in seen:
                    seen[hit["id"]] = True
                    parts.append(f"[{hit['id']}] ({hit['source']})\n{hit['text']}")
        return "\n\n".join(parts), list(seen)
