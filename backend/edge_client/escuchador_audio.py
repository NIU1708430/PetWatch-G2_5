import base64
import time
import os
from google.cloud import firestore
import pygame

# Inicializamos el reproductor de audio
pygame.mixer.init()

# Conectamos a tu base de datos específica
db = firestore.Client(project="petwatch-sm", database="petwatch-db")

def reproducir_audio(cambios_docs, objeto_contexto, hora_lectura):
    """Se ejecuta AUTOMÁTICAMENTE cada vez que entra un audio nuevo en Firestore"""
    for cambio in cambios_docs:
        # Solo nos interesan los documentos que se acaban de AÑADIR
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            # Si el audio no ha sido reproducido todavía
            if datos.get('reproducido') is False:
                print("🎤 ¡Entrando audio desde la web PetWatch!")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    # Decodificamos el Base64 a un archivo físico temporal .wav
                    bytes_audio = base64.b64decode(audio_b64)
                    nombre_archivo = "mensaje_robot.wav"
                    
                    with open(nombre_archivo, "wb") as archivo_wav:
                        archivo_wav.write(bytes_audio)
                    
                    # Reproducir el sonido por los altavoces
                    try:
                        pygame.mixer.music.load(nombre_archivo)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.1) # Esperamos a que termine de hablar
                        pygame.mixer.music.unload()
                        
                        # Borramos el archivo temporal
                        os.remove(nombre_archivo)
                    except Exception as audio_error:
                        print(f"Error al reproducir el altavoz: {audio_error}")

                # Marcamos el audio como REPRODUCIDO en Firestore para no repetir en bucle
                cambio.document.reference.update({'reproducido': True})
                print("✅ Mensaje emitido y marcado como leído.\n")

# Ponemos a Firestore en modo "escucha activa en tiempo real" (Snapshot Listener)
print("📡 Robot escuchando el canal de audio de PetWatch... Habla desde la web.")
coleccion_audio_ref = db.collection("comandos_audio")
observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

# Mantener el script corriendo para siempre
while True:
    time.sleep(1)