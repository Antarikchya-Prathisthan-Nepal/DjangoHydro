import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, r'C:\Users\Dell\antar\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')

import torch, joblib

BASE = r'C:\Users\Dell\antar\DjangoHydro\Hydro_WebPortal'

# ── Scalers ──────────────────────────────────────────────────────────────────
inp_scaler = joblib.load(os.path.join(BASE, 'models/scalers/UM_input_scaler_365day_45ahead.pkl'))
out_scaler = joblib.load(os.path.join(BASE, 'models/scalers/UM_discharge_scaler_365day_45ahead.pkl'))

print('=== Input Scaler ===')
print('  type             :', type(inp_scaler).__name__)
print('  n_features_in_   :', getattr(inp_scaler, 'n_features_in_', 'N/A'))
print('  feature_range    :', getattr(inp_scaler, 'feature_range', 'N/A'))
print()
print('=== Output Scaler ===')
print('  type             :', type(out_scaler).__name__)
print('  n_features_in_   :', getattr(out_scaler, 'n_features_in_', 'N/A'))
print()

# ── Model ────────────────────────────────────────────────────────────────────
d = torch.load(os.path.join(BASE, 'models/pytorch/UM_LSTM_45day.pt'), map_location='cpu', weights_only=False)
sd = d['model_state_dict']

print('=== Model State Dict Layers ===')
for k, v in sd.items():
    if hasattr(v, 'shape'):
        print(f'  {k}: {tuple(v.shape)}')

wih = sd['lstm.weight_ih_l0']
input_size  = wih.shape[1]
hidden_size = wih.shape[0] // 4
print()
print('=== Derived Architecture ===')
print('  input_size  (n_features) :', input_size)
print('  hidden_size              :', hidden_size)
print('  epoch trained to         :', d.get('epoch'))
print('  val_loss                 :', d.get('val_loss'))
print()
print('=== Mismatch Check ===')
print('  scaler n_features :', inp_scaler.n_features_in_)
print('  model  input_size :', input_size)
print('  MATCH             :', inp_scaler.n_features_in_ == input_size)
