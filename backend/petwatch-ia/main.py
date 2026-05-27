import base64
import cv2
import numpy as np
import functions_framework

# Importamos vuestros "trabajadores"
from yolo_detector import detectar_animal
from pose_estimator import estimar_esqueleto
# from heuristics import clasificar_postura  

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
    caja_animal = detectar_animal(frame_completo) 

    if caja_animal is None:
        return 

    # 4. PASO 2: RECORTAR (CROPPING)
    x1, y1, x2, y2 = caja_animal
    recorte_mascota = frame_completo[y1:y2, x1:x2]

    # 5. PASO 3: ESQUELETO CON RESNET
    puntos_clave = estimar_esqueleto(recorte_mascota)

    if puntos_clave is None:
        return

    # 6. PASO 4: HEURÍSTICA (Adivinar la acción)
    from heuristics import analizar_postura
    accion = analizar_postura(puntos_clave)
    
    print(f"¡RESULTADO FINAL! La mascota está: {accion}")