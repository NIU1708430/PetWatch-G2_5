import os
from google.cloud import storage

# ================= CONFIGURACIÓN =================
BUCKET_NAME = "petwatch_modelos_ia"
MODEL_FILE_NAME = "modelo4.pt"  
# =================================================

# Variable global para mantener el modelo cargado entre peticiones 
model = None
LOCAL_MODEL_PATH = f"/tmp/{MODEL_FILE_NAME}"

def descargar_modelo_yolo():
    """
    Descarga el modelo de YOLO del Bucket a la memoria temporal (/tmp) de la Cloud Function.
    Si ya se descargó en una ejecución anterior, se salta este paso.
    """
    global model
    if model is None:
        # Importamos ultralytics solo cuando la función se ejecuta por primera vez
        from ultralytics import YOLO
        
        print(f"[YOLO] Descargando {MODEL_FILE_NAME} desde el bucket {BUCKET_NAME}...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(MODEL_FILE_NAME)
        
        blob.download_to_filename(LOCAL_MODEL_PATH)
        
        # Cargamos el modelo
        model = YOLO(LOCAL_MODEL_PATH)
        print("[YOLO] OK - Modelo inicializado y listo para trabajar.")

def detectar_animal(frame):
    """
    Recibe un fotograma (frame) de OpenCV.
    Devuelve:
      - Una lista [x1, y1, x2, y2] con las coordenadas de la caja de la mascota.
      - None si no detecta nada o hay un error.
    """
    # 1. Asegurarnos de que el modelo está listo
    descargar_modelo_yolo()

    if frame is None:
        print("[YOLO] Error: El fotograma recibido está vacío.")
        return None

    try:
        # 2. Inferencia (Buscamos a la mascota con un 50% de seguridad mínima)
        resultados = model(frame, conf=0.5)

        # 3. Analizar la respuesta de YOLO
        for resultado in resultados:
            if hasattr(resultado, 'boxes') and len(resultado.boxes) > 0:
                
                # Cogemos solo el primer animal que detecte 
                caja_principal = resultado.boxes[0]
                
                # Datos extra 
                clase_id = int(caja_principal.cls[0])
                nombre_clase = model.names[clase_id]
                confianza = float(caja_principal.conf[0]) * 100
                
                # Coordenadas exactas: Pasamos los tensores de PyTorch a números enteros estándar
                coordenadas_array = caja_principal.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = coordenadas_array
                
                print(f"[YOLO] ¡Mascota Localizada! -> {nombre_clase.upper()} al {confianza:.1f}%. Caja: [{x1}, {y1}, {x2}, {y2}]")
                
                # 4. Devolvemos las coordenadas al 'main.py' para que haga el recorte
                return [x1, y1, x2, y2], nombre_clase

        print("[YOLO] La habitación parece estar vacía (No se superó el 50% de confianza).")
        return None
        
    except Exception as e:
        print(f"[YOLO] Error crítico durante la inferencia: {e}")
        return None