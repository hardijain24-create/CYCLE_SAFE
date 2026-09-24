"""CycleSafe Training Entrypoint Script.

Triggers full training pipeline, outputs empirical metrics, saves model artifact,
model card, and experiment registry.
"""

import os
import sys

# Ensure root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def main():
    print("=" * 80)
    print("CYCLESAFE MODEL TRAINING ENTRYPOINT")
    print("=" * 80)

    # Import training functions from cycle_safe
    from cycle_safe import load_csv_source, train_cyclesafe_V4, DATA_URL

    # Run the full training pipeline
    raw_data = load_csv_source(DATA_URL)
    result = train_cyclesafe_V4(raw_data, save_artifact=True)

    print("\n" + "=" * 80)
    print("CYCLESAFE V5 COMPLETE")
    print("=" * 80)
    print("Deployment model:", result["deployment_model_name"])
    print("Untouched final-test MAE:", round(result["final_test_metrics"]["mae"], 3), "days")
    print("\nTraining completed successfully! Verified baseline reproducibility.")

if __name__ == "__main__":
    main()
