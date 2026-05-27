import base64
import cv2
import numpy as np
import functions_framework
from google.cloud import firestore

from yolo_detector import detectar_animal
from pose_estimator import estimar_esqueleto
# from heuristics import clasificar_postura  

db = firestore.Client(project="petwatch-sm", database="petwatch-db")

@functions_framework.cloud_event
def procesar_ia_mascotas(cloud_event):
    """
    Punto de entrada de la Cloud Function. Se ejecuta automáticamente 
    cada vez que la Raspberry Pi manda un mensaje a Pub/Sub.
    """
    # 1. LEER EL MENSAJE DE PUB/SUB
    pubsub_message = cloud_event.data.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        print("Error: El mensaje de Pub/Sub ha llegado vacío.")
        return

    # 2. RECONSTRUIR LA IMAGEN
    img_bytes = base64.b64decode(pubsub_message["data"])
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame_completo = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

    if frame_completo is None:
        print("Error: No se pudo decodificar el fotograma.")
        return

    print("Fotograma recibido. Iniciando Pipeline de IA...")

    # 3. PASO 1: LOCALIZAR CON YOLO
    resultado_yolo = detectar_animal(frame_completo) 

    if resultado_yolo is None:
        return 

    # Desempaquetamos la caja y el nombre del animal
    caja_animal, tipo_animal = resultado_yolo

    # 4. PASO 2: RECORTAR (CROPPING)
    x1, y1, x2, y2 = caja_animal
    recorte_mascota = frame_completo[y1:y2, x1:x2]   # <-- ¡FALTA ESTA LÍNEA!

    # 5. PASO 3: ESQUELETO CON RESNET
    puntos_clave = estimar_esqueleto(recorte_mascota)
    if puntos_clave is None:
        return

    # 6. PASO 4: HEURÍSTICA 
    from heuristics import analizar_postura
    accion = analizar_postura(puntos_clave)

    print(f"¡RESULTADO FINAL! Detectado {tipo_animal} que está: {accion}")
  
    # 7. GUARDAR EN FIRESTORE 
    datos_mascota = {
        "animal": tipo_animal, 
        "postura": accion,
        "fecha_hora": firestore.SERVER_TIMESTAMP
    }

    try:
        db.collection("historial_mascotas").add(datos_mascota)
        print("Guardado en Firestore correctamente.")
    except Exception as e:
        print(f"Error al guardar en Firestore: {e}")