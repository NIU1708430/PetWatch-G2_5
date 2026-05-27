# pose_estimator.py

import os
import torch
import cv2
from torchvision import transforms
from PIL import Image
from google.cloud import storage
from PoseEstimationTrain2 import SimplePoseModel 

# ================= CONFIGURACIÓN =================
BUCKET_NAME = "petwatch_modelos_ia"
MODEL_FILE_NAME = "best_ap10k_pose_estimation_model.pth"
NUM_KEYPOINTS = 17
# =================================================

modelo_pose = None
LOCAL_MODEL_PATH = f"/tmp/{MODEL_FILE_NAME}"

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Transformaciones que teníais en vuestro código
transform_modelo = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

def descargar_modelo_resnet():
    """Descarga e inicializa vuestro modelo personalizado AP-10K."""
    global modelo_pose
    if modelo_pose is None:
        print(f"[RESNET] Descargando {MODEL_FILE_NAME} desde {BUCKET_NAME}...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(MODEL_FILE_NAME)
        blob.download_to_filename(LOCAL_MODEL_PATH)
        
        # Instanciar el modelo vacío y cargarle vuestros pesos
        modelo_pose = SimplePoseModel(num_keypoints=NUM_KEYPOINTS)
        modelo_pose.load_state_dict(torch.load(LOCAL_MODEL_PATH, map_location=device))
        modelo_pose.to(device).eval()
        print("[RESNET] OK - Modelo inicializado.")

def estimar_esqueleto(imagen_recortada):
    """
    Recibe el recorte de YOLO. Devuelve la matriz NumPy de puntos normalizados.
    """
    descargar_modelo_resnet()

    if imagen_recortada is None or imagen_recortada.size == 0:
        return None

    try:
        # Preprocesar la imagen OpenCV (BGR) a formato PIL (RGB) para vuestras transformaciones
        img_pil = Image.fromarray(cv2.cvtColor(imagen_recortada, cv2.COLOR_BGR2RGB))
        img_tensor = transform_modelo(img_pil).unsqueeze(0).to(device)
        
        # Inferencia
        with torch.no_grad():
            output = modelo_pose(img_tensor)
            # Extraemos la matriz (17, 2) que vuestra heurística espera
            points_norm = output.cpu().view(NUM_KEYPOINTS, 2).numpy()
            
        return points_norm

    except Exception as e:
        print(f"[RESNET] Error durante la extracción del esqueleto: {e}")
        return None