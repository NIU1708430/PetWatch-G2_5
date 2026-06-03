# PoseEstimationTrain2.py

import torch.nn as nn
from torchvision import models
from torchvision.models import ResNet50_Weights

class SimplePoseModel(nn.Module):
    """
    Clase estructural para cargar los pesos de 'best_ap10k_pose_estimation_model.pth'
    en Google Cloud Functions.
    """
    def __init__(self, num_keypoints=17):
        super(SimplePoseModel, self).__init__()
        
        # 1. Instanciamos la ResNet-50 original
        weights = ResNet50_Weights.DEFAULT
        self.backbone = models.resnet50(weights=weights)
        
        # 2. Modificamos la última capa (Fully Connected - fc) para que devuelva
        # 34 valores (17 keypoints x 2 coordenadas) 
        num_ftrs = self.backbone.fc.in_features
        self.backbone.fc = nn.Linear(num_ftrs, num_keypoints * 2)

    def forward(self, x):
        # La imagen atraviesa la red y devuelve el tensor con las coordenadas
        return self.backbone(x)