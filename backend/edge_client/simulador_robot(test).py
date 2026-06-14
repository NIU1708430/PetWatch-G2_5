import os
from google.cloud import pubsub_v1

PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
IMAGE_PATH = "perro_prueba2.jpg"  

def main():
    print("Iniciando Mock del entorno Edge...")
    
    if not os.path.exists(IMAGE_PATH):
        print(f"Error de I/O: El archivo de prueba '{IMAGE_PATH}' no se encuentra en el directorio de trabajo.")
        return

    # Empaquetado binario del archivo estatico
    with open(IMAGE_PATH, "rb") as image_file:
        image_bytes = image_file.read()
        
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        
        # Inyeccion de la carga util en la cola de mensajeria
        future = publisher.publish(topic_path, image_bytes)
        print(f"Mock ejecutado. Payload inyectado en Pub/Sub con ID: {future.result()}")
        print("Revisa los logs de Google Cloud Functions para verificar el pipeline de inferencia.")
    except Exception as e:
        print(f"Excepcion en la cola de mensajeria: {e}")

if __name__ == "__main__":
    main()