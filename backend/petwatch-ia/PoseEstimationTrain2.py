import torch.nn as nn
from torchvision import models
from torchvision.models import ResNet50_Weights

class SimplePoseModel(nn.Module):
    # Blueprint arquitectonico derivado de Transfer Learning
    def __init__(self, num_keypoints=17):
        super(SimplePoseModel, self).__init__()
        
        # Instanciacion de la red troncal (Backbone) preentrenada en ImageNet
        weights = ResNet50_Weights.DEFAULT
        self.backbone = models.resnet50(weights=weights)
        
        # Sustitucion de la ultima capa densa (Softmax clasificatorio original de 1000 clases)
        # por una capa de regresion lineal para predecir las coordenadas continuas de los joints (x, y)
        num_ftrs = self.backbone.fc.in_features
        self.backbone.fc = nn.Linear(num_ftrs, num_keypoints * 2)

    def forward(self, x):
        # Propagacion hacia delante (Forward pass)
        return self.backbone(x)