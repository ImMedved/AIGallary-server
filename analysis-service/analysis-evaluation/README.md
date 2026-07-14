# Analysis Evaluation Harness

This directory contains the baseline dataset, expected annotations, raw evaluation
results, and generated reports used to measure the analysis service across stages.

## Layout

```text
analysis-evaluation/
  images/
  expected/
  results/
  reports/
  tools/
```

## Generate Synthetic Baseline Dataset

The synthetic dataset generator uses only the Java standard library so it can run
on machines that do not have Python imaging dependencies installed locally.

```powershell
javac analysis-evaluation\tools\SyntheticDatasetGenerator.java
java -cp analysis-evaluation\tools SyntheticDatasetGenerator
```

## Run Evaluation

Start the analysis service first, then run:

```powershell
python analysis-evaluation\evaluate.py --base-url http://127.0.0.1:8090
```

The script stores per-image raw responses in `results/` and aggregate reports in
`reports/`.
