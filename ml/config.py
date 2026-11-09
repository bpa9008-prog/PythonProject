"""Константы ML-пайплайна: пути, имена колонок, параметры разбиения."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "cardio_train.csv"
SPLITS_DIR = PROJECT_ROOT / "data" / "splits"
MODEL_PATH = PROJECT_ROOT / "models" / "model.pkl"
REPORTS_DIR = PROJECT_ROOT / "reports"

TARGET = "cardio"
ID_COLUMN = "id"

# Исходные признаки датасета. age — в днях, height — в см, weight — в кг,
# ap_hi / ap_lo — верхнее и нижнее давление, мм рт. ст.
RAW_NUMERIC = ["age", "height", "weight", "ap_hi", "ap_lo"]
RAW_CATEGORICAL = ["gender", "cholesterol", "gluc", "smoke", "alco", "active"]

# Признаки-кандидаты для отбора: часть исходных + сконструированные (ml/features.py).
CANDIDATE_NUMERIC = ["age_years", "height", "weight", "bmi", "ap_hi", "ap_lo", "pulse_pressure"]
CANDIDATE_CATEGORICAL = RAW_CATEGORICAL

RANDOM_STATE = 42
TEST_SIZE = 0.2

# Порог значимости признака: |корреляция Пирсона| для числовых и V Крамера для категориальных.
# Это две разные шкалы, поэтому один порог — эвристика для отсева заведомо слабых признаков,
# а не статистический критерий значимости.
RELEVANCE_THRESHOLD = 0.05
# Из пары числовых признаков с |корреляцией| выше порога оставляем один.
COLLINEARITY_THRESHOLD = 0.8
