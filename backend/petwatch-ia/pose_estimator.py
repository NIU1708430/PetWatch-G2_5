import os
import torch
import cv2
from torchvision import transforms
from PIL import Image
from google.cloud import storage
from PoseEstimationTrain2 import SimplePoseModel 

BUCKET_NAME = "petwatch_modelos_ia"
MODEL_FILE_NAME = "best_ap10k_pose_estimation_model.pth"
NUM_KEYPOINTS = 17

modelo_pose = None
LOCAL_MODEL_PATH = f"/tmp/{MODEL_FILE_NAME}"

# Offloading a GPU en caso de que la Function Scale esté aprovisionada con CUDA
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Pipeline de preprocesamiento de tensores estandarizado para redes preentrenadas
transform_modelo = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

def descargar_modelo_resnet():
    # Cacheo del modelo en el ecosistema /tmp para penalizar la red solo en el arranque en frío
    global modelo_pose
    if modelo_pose is None:
        print(f"Inicializando instancia ResNet desde blob {MODEL_FILE_NAME}...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(MODEL_FILE_NAME)
        blob.download_to_filename(LOCAL_MODEL_PATH)
        
        # Mapeo de pesos a la arquitectura definida y transicion a modo inferencia
        modelo_pose = SimplePoseModel(num_keypoints=NUM_KEYPOINTS)
        modelo_pose.load_state_dict(torch.load(LOCAL_MODEL_PATH, map_location=device))
        modelo_pose.to(device).eval()

def estimar_esqueleto(imagen_recortada):
    descargar_modelo_resnet()

    if imagen_recortada is None or imagen_recortada.size == 0:
        return None

    try:
        # Conversión del espacio de color nativo de OpenCV (BGR) a formato estandar PIL (RGB)
        img_pil = Image.fromarray(cv2.cvtColor(imagen_recortada, cv2.COLOR_BGR2RGB))
        
        # Vectorizacion añadiendo dimensión de batch requerida por PyTorch
        img_tensor = transform_modelo(img_pil).unsqueeze(0).to(device)
        
        # Inferencia desactivando el tracking de gradientes para optimizar la RAM y ciclos CPU
        with torch.no_grad():
            output = modelo_pose(img_tensor)
            # Reestructuracion del tensor unidimensional de 34 a una matriz (17 nodos x 2 coordenadas)
            points_norm = output.cpu().view(NUM_KEYPOINTS, 2).numpy()
            
        return points_norm

    except Exception as e:
        print(f"Error tensorial en Pose Estimation: {e}")
        return None