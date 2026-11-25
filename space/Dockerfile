# Se construye desde la raíz del repo (scripts/publicar_space.py sube el contexto): la consola importa core/ y scripts/.
FROM python:3.11-slim
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user space/requirements.txt space/requirements.txt
RUN pip install --no-cache-dir -r space/requirements.txt
COPY --chown=user . .
USER user
ENV HOME=/home/user PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_EXPERIMENTAL_WARNING=1
EXPOSE 7860
CMD ["uvicorn", "space.app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
