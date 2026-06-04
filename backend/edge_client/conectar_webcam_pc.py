import time
import cv2  
from google.cloud import pubsub_v1

# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
# =================================================

def main():
    print("==================================================")
    print("    PETWATCH CLOUD - TRANSMISIÓN DESDE PC         ")
    print("==================================================")

    # 1. Conexión con Google Cloud Pub/Sub
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> Conexión establecida correctamente.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 2. Inicialización de la Webcam del portátil 
    print("Iniciando la webcam del PC con OpenCV...")
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: No se pudo encender la cámara web de tu portátil.")
        return

    print("\n[OK] Webcam lista y transmitiendo.")
    print("--> Para detener la transmisión, pulsa Ctrl + C en esta terminal.")
    print("==================================================\n")

    try:
        while True:
            # Capturar un fotograma de la webcam
            ret, frame = cap.read()
            
            if not ret:
                print("Error al leer el fotograma de la webcam.")
                continue

            # Comprimir la imagen a formato JPG 
            _, buffer = cv2.imencode('.jpg', frame)
            img_bytes = buffer.tobytes()

            try:
                # Enviar los bytes comprimidos directamente a Google Cloud Pub/Sub
                future = publisher.publish(topic_path, img_bytes)
                print(f"[{time.strftime('%H:%M:%S')}] Fotograma enviado con éxito. ID: {future.result()}")
            except Exception as pub_error:
                print(f"Error al enviar a Pub/Sub: {pub_error}")

            # Enviar 1 fotograma cada 5 segundos 
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nTransmisión detenida de forma manual desde la terminal.")
    finally:
        # Cerrar la cámara de forma segura
        cap.release()
        print("Cámara apagada correctamente. ¡Proyecto cerrado!")

if __name__ == "__main__":
    main()