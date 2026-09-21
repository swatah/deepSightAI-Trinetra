#!/bin/bash

echo "Starting deepSightAI Trinetra Embedder Service..."

# Check if ONNX model exists, if not try to export it
if [ ! -f "models/open_clip_vit_b32.onnx" ]; then
    echo "ONNX model not found. Checking for PyTorch model..."
    
    if [ -f "models/open_clip_pytorch_model.bin" ]; then
        echo "PyTorch model found. Exporting to ONNX..."
        python export_to_onnx.py
        if [ $? -eq 0 ]; then
            echo "ONNX export successful"
        else
            echo "ONNX export failed, continuing with PyTorch model"
        fi
    else
        echo "No local models found. Will download model on first run."
    fi
else
    echo "ONNX model already exists"
fi

echo "Starting embedder service..."
python embedder.py
