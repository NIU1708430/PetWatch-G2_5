import base64
import time
import os
import subprocess
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
                    # Definimos los nombres de los archivos temporales
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    # Decodificamos el Base64 tal y como viene de la web
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # --- CONVERSIÓN CON FFMPEG ---
                        # Transforma el contenedor WebM/Opus de Chrome en un WAV Estándar (PCM 16-bit)
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '16000', 
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # Reproducir el sonido limpio por los altavoces
                        pygame.mixer.music.load(archivo_salida)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.1) # Esperamos a que termine de hablar
                        pygame.mixer.music.unload()
                        print("✅ Mensaje emitido por el altavoz.")
                        
                    except subprocess.CalledProcessError:
                        print("❌ Error: FFMPEG falló al convertir el formato del audio.")
                    except Exception as audio_error:
                        print(f"❌ Error al reproducir en el altavoz: {audio_error}")
                    finally:
                        # Limpieza estricta de archivos temporales
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                # Marcamos el audio como REPRODUCIDO en Firestore para evitar bucles
                cambio.document.reference.update({'reproducido': True})
                print("📌 Documento marcado como leído en la base de datos.\n")

# Ponemos a Firestore en modo "escucha activa en tiempo real"
print("📡 Robot escuchando el canal de audio de PetWatch... Habla desde la web.")
coleccion_audio_ref = db.collection("comandos_audio")
observador = coleccion_audio_ref.on_snapshot(reproducir_audio)

# Mantener el script corriendo para siempre
while True:
    time.sleep(1)