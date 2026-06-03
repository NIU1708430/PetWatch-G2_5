import os
from google.cloud import pubsub_v1

# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
IMAGE_PATH = "perro_prueba.jpg"  
# =================================================

def main():
    print("==================================================")
    print("      PETWATCH CLOUD - SIMULADOR EDGE             ")
    print("==================================================")
    
    print(f"Preparando simulador con la imagen: {IMAGE_PATH}")
    
    # 1. Verificar que la imagen existe
    if not os.path.exists(IMAGE_PATH):
        print(f"Error: No encuentro el archivo '{IMAGE_PATH}' en esta carpeta.")
        return

    # 2. Leer la imagen directamente como bytes
    print("Empaquetando la foto...")
    with open(IMAGE_PATH, "rb") as image_file:
        image_bytes = image_file.read()
        
    # 3. Conectar a Pub/Sub
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        
        # 4. Enviar la imagen al buzón
        future = publisher.publish(topic_path, image_bytes)
        print(f"¡Fotograma enviado con éxito a la nube! ID: {future.result()}")
        print("==================================================")
        print("Ve a los registros de Google Cloud Run para ver qué piensa la IA.")
    except Exception as e:
        print(f"Error al conectar o enviar a Pub/Sub: {e}")

if __name__ == "__main__":
    main()