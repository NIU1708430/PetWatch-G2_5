import os
import base64
import cv2
import numpy as np
import functions_framework
from google.cloud import storage

# ================= CONFIGURACIÓN =================
BUCKET_NAME = "petwatch_modelos_ia"
MODEL_FILE_NAME = "modelo4.pt"  
# =================================================

model = None
LOCAL_MODEL_PATH = f"/tmp/{MODEL_FILE_NAME}"

def descargar_modelo_yolo():
    global model
    if model is None:
        from ultralytics import YOLO
        
        print(f"Iniciando descarga de {MODEL_FILE_NAME} desde el bucket {BUCKET_NAME}...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(MODEL_FILE_NAME)
        
        blob.download_to_filename(LOCAL_MODEL_PATH)
        model = YOLO(LOCAL_MODEL_PATH)
        print("[OK] Modelo YOLO inicializado en la nube.")

@functions_framework.cloud_event
def procesar_ia_mascotas(cloud_event):
    descargar_modelo_yolo()

    pubsub_message = cloud_event.data.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        print("Error: El mensaje de Pub/Sub ha llegado vacío.")
        return

    # Extraer y reconstruir la imagen
    img_bytes = base64.b64decode(pubsub_message["data"])
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

    if frame is None:
        print("Error: No se pudo decodificar el fotograma.")
        return

    # Inferencia con YOLO (50% de umbral de confianza)
    resultados = model(frame, conf=0.5)

    # Imprimir resultados en los registros (Logs)
    for resultado in resultados:
        if hasattr(resultado, 'boxes') and len(resultado.boxes) > 0:
            for box in resultado.boxes:
                clase_id = int(box.cls[0])
                nombre_clase = model.names[clase_id]
                confianza = float(box.conf[0])
                print(f"-> [{nombre_clase.upper()}] detectado con {(confianza*100):.1f}% de certeza.")

    print("Procesamiento del fotograma finalizado.")