import torch
import open_clip
import os

def export_model():
    print("Loading OpenCLIP model...")
    
    # Check if local PyTorch model exists, otherwise use pretrained
    local_pytorch_model = "models/open_clip_pytorch_model.bin"
    if os.path.exists(local_pytorch_model):
        print(f"Using local PyTorch model: {local_pytorch_model}")
        pretrained_source = local_pytorch_model
    else:
        print("Using online pretrained model: laion2b_s34b_b79k")
        pretrained_source = "laion2b_s34b_b79k"
    
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=pretrained_source
    )
    model.eval()
    
    # Create models directory if it doesn't exist
    os.makedirs("models", exist_ok=True)
    
    # Create dummy input (batch_size=1, channels=3, height=224, width=224)
    dummy_input = torch.randn(1, 3, 224, 224)
    
    print("Exporting to ONNX...")
    # Export only the vision encoder part
    torch.onnx.export(
        model.visual,  # Only export the vision part
        dummy_input,
        "models/open_clip_vit_b32.onnx",
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={
            'input': {0: 'batch_size'},    # Variable batch size
            'output': {0: 'batch_size'}
        }
    )
    
    print("✅ Model exported to models/open_clip_vit_b32.onnx")
    
    # Test the exported model
    print("Testing ONNX model...")
    try:
        import onnxruntime as ort
        import numpy as np
        
        session = ort.InferenceSession("models/open_clip_vit_b32.onnx")
        test_input = np.random.randn(2, 3, 224, 224).astype(np.float32)
        result = session.run(None, {session.get_inputs()[0].name: test_input})
        print(f"ONNX model test successful. Output shape: {result[0].shape}")
    except ImportError:
        print("onnxruntime not installed. Install it to test the exported model.")
    except Exception as e:
        print(f"ONNX model test failed: {e}")

if __name__ == "__main__":
    export_model()
