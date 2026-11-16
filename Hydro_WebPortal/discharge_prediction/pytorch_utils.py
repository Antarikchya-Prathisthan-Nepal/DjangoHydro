import torch.nn as nn
class GRUModel(nn.Module):
    def __init__(self, input_size, hidden_size=50, num_layers=2, dropout=0.2):
        super(GRUModel, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.gru = nn.GRU(input_size, hidden_size, num_layers,
                         batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        gru_out, _ = self.gru(x)
        gru_out = self.dropout(gru_out[:, -1, :])  # Take last output
        output = self.fc(gru_out)
        return output
class LSTMModel(nn.Module):
    def __init__(self, input_size, hidden_size=50, num_layers=2, dropout=0.2):
        super(LSTMModel, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, 
                            batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 1)
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        lstm_out = self.dropout(lstm_out[:, -1, :])
        output = self.fc(lstm_out)
        return output
"""
PyTorch utilities for discharge prediction models
"""
import torch
import torch.nn as nn
import numpy as np
import logging
from typing import Optional, Tuple, Union
import os

logger = logging.getLogger(__name__)

class DischargePredictionNet(nn.Module):
    """
    Example PyTorch neural network architecture for discharge prediction
    
    Input: (batch_size, sequence_length, n_features) = (batch_size, 90, 5)
    Output: (batch_size, 1) - predicted discharge
    """
    
    def __init__(self, 
                 input_size: int = 5,           # Number of ERA5 features
                 sequence_length: int = 90,      # Input sequence length
                 hidden_size: int = 128,         # LSTM hidden size
                 num_layers: int = 2,            # Number of LSTM layers
                 dropout: float = 0.2,           # Dropout rate
                 output_size: int = 1):          # Output size (discharge prediction)
        """
        Initialize the neural network
        
        Args:
            input_size: Number of input features (5 for ERA5 data)
            sequence_length: Length of input sequence (90 days)
            hidden_size: Size of LSTM hidden state
            num_layers: Number of LSTM layers
            dropout: Dropout probability
            output_size: Number of output predictions (1 for discharge)
        """
        super(DischargePredictionNet, self).__init__()
        
        self.input_size = input_size
        self.sequence_length = sequence_length
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        
        # Input normalization layer
        self.input_norm = nn.BatchNorm1d(input_size)
        
        # LSTM layers for sequence processing
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=True
        )
        
        # Attention mechanism (optional)
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size * 2,  # Bidirectional LSTM
            num_heads=8,
            dropout=dropout,
            batch_first=True
        )
        
        # Fully connected layers
        self.fc_layers = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(), 
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, output_size),
            nn.ReLU()  # Ensure positive discharge prediction
        )
        
        # Initialize weights
        self._init_weights()
    
    def _init_weights(self):
        """Initialize model weights"""
        for name, param in self.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param.data)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param.data)
            elif 'bias' in name:
                param.data.fill_(0)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through the network
        
        Args:
            x: Input tensor of shape (batch_size, sequence_length, input_size)
            
        Returns:
            Output tensor of shape (batch_size, output_size)
        """
        batch_size, seq_len, input_size = x.shape
        
        # Normalize input features across the sequence dimension
        # Reshape for batch normalization: (batch_size * seq_len, input_size)
        x_reshaped = x.view(-1, input_size)
        x_norm = self.input_norm(x_reshaped)
        x = x_norm.view(batch_size, seq_len, input_size)
        
        # LSTM processing
        lstm_out, (hidden, cell) = self.lstm(x)
        
        # Apply attention mechanism
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        
        # Use the last time step output
        final_output = attn_out[:, -1, :]  # (batch_size, hidden_size * 2)
        
        # Pass through fully connected layers
        discharge_prediction = self.fc_layers(final_output)
        
        return discharge_prediction
    
    def predict(self, x: Union[np.ndarray, torch.Tensor]) -> np.ndarray:
        """
        Make predictions (compatible with sklearn-style interface)
        
        Args:
            x: Input data as numpy array or torch tensor
            
        Returns:
            Predictions as numpy array
        """
        self.eval()
        with torch.no_grad():
            if isinstance(x, np.ndarray):
                x = torch.FloatTensor(x)
            
            predictions = self.forward(x)
            
            if hasattr(predictions, 'cpu'):
                return predictions.cpu().numpy()
            else:
                return predictions.detach().numpy()


class PyTorchModelValidator:
    """Utility class for validating PyTorch discharge prediction models"""
    
    def __init__(self, sequence_length: int = 90, n_features: int = 5):
        self.sequence_length = sequence_length
        self.n_features = n_features
    
    def validate_model_structure(self, model: nn.Module) -> Tuple[bool, str]:
        """
        Validate that the model has the expected structure for discharge prediction
        
        Returns:
            (is_valid, message)
        """
        try:
            # Test input shape
            test_input = torch.randn(1, self.sequence_length, self.n_features)
            
            # Test forward pass
            model.eval()
            with torch.no_grad():
                output = model(test_input)
            
            # Check output shape
            if output.shape[0] != 1:
                return False, f"Expected batch dimension 1, got {output.shape[0]}"
            
            if len(output.shape) != 2 or output.shape[1] != 1:
                return False, f"Expected output shape (batch_size, 1), got {output.shape}"
            
            # Check for reasonable output values
            output_val = output.item()
            if output_val < 0:
                return False, f"Model produced negative discharge: {output_val}"
            
            if output_val > 10000:  # Sanity check for extremely high discharge
                return False, f"Model produced unrealistic high discharge: {output_val}"
            
            return True, "Model validation successful"
            
        except Exception as e:
            return False, f"Model validation failed: {str(e)}"
    
    def validate_saved_model(self, model_path: str) -> Tuple[bool, str, Optional[nn.Module]]:
        """
        Validate a saved PyTorch model file
        
        Returns:
            (is_valid, message, loaded_model)
        """
        try:
            if not os.path.exists(model_path):
                return False, f"Model file not found: {model_path}", None
            
            # Load the model
            model = torch.load(model_path, map_location='cpu')
            
            # Check if it's actually a PyTorch model
            if not isinstance(model, nn.Module):
                return False, f"Loaded object is not a PyTorch model: {type(model)}", None
            
            # Validate structure
            is_valid, message = self.validate_model_structure(model)
            
            if is_valid:
                return True, message, model
            else:
                return False, message, None
                
        except Exception as e:
            return False, f"Failed to load model: {str(e)}", None
    
    def create_sample_model(self, save_path: Optional[str] = None) -> nn.Module:
        """
        Create a sample model for testing purposes
        
        Args:
            save_path: Optional path to save the model
            
        Returns:
            Sample PyTorch model
        """
        model = DischargePredictionNet(
            input_size=self.n_features,
            sequence_length=self.sequence_length,
            hidden_size=64,  # Smaller for demo
            num_layers=2,
            dropout=0.1
        )
        
        if save_path:
            torch.save(model, save_path)
            logger.info(f"Sample model saved to {save_path}")
        
        return model


def load_pytorch_model(model_path: str, 
                      map_location: str = 'cpu',
                      validate_structure: bool = True) -> Tuple[nn.Module, bool, str]:
    """
    Load and validate a PyTorch model for discharge prediction
    
    Args:
        model_path: Path to the saved model
        map_location: Device to load the model on
        validate_structure: Whether to validate model structure
        
    Returns:
        (model, is_valid, message)
    """
    try:
        # Load the model
        model = torch.load(model_path, map_location=map_location)
        
        if not isinstance(model, nn.Module):
            return None, False, f"Loaded object is not a PyTorch model: {type(model)}"
        
        # Set to evaluation mode
        model.eval()
        
        # Validate structure if requested
        if validate_structure:
            validator = PyTorchModelValidator()
            is_valid, message = validator.validate_model_structure(model)
            return model, is_valid, message
        
        return model, True, "Model loaded successfully"
        
    except Exception as e:
        return None, False, f"Failed to load PyTorch model: {str(e)}"


def save_pytorch_model(model: nn.Module, 
                      save_path: str,
                      validate_before_save: bool = True) -> Tuple[bool, str]:
    """
    Save a PyTorch model with optional validation
    
    Args:
        model: PyTorch model to save
        save_path: Path to save the model
        validate_before_save: Whether to validate before saving
        
    Returns:
        (success, message)
    """
    try:
        if validate_before_save:
            validator = PyTorchModelValidator()
            is_valid, message = validator.validate_model_structure(model)
            if not is_valid:
                return False, f"Model validation failed: {message}"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Save the model
        torch.save(model, save_path)
        
        return True, f"Model saved successfully to {save_path}"
        
    except Exception as e:
        return False, f"Failed to save model: {str(e)}"
