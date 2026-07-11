DEFAULT_CLIP_TAGS = [
    "screenshot", "document", "receipt", "invoice", "meme", "text", "chat screenshot", "code screenshot",
    "game screenshot", "anime", "illustration", "drawing", "portrait", "selfie", "group photo", "people",
    "face", "cat", "dog", "pet", "food", "drink", "coffee", "restaurant", "street", "city", "building",
    "transport", "vehicle", "car", "bus", "bus stop", "train", "airplane", "boat", "nature", "forest",
    "mountain", "sea", "beach", "snow", "home", "interior", "office", "computer", "monitor", "keyboard",
    "phone", "table", "sofa", "bedroom", "kitchen", "books", "bookshelf", "library", "screen", "sign",
    "poster", "whiteboard", "paper", "handwritten text", "printed text", "night", "party", "sports", "flower",
    "animal", "sky", "water", "road", "shop", "clothes", "toy", "art", "map", "diagram",
]

TRANSPORT_LABELS = {"bicycle", "car", "motorbike", "motorcycle", "bus", "train", "truck", "boat", "airplane"}
ANIMAL_LABELS = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
FURNITURE_LABELS = {"chair", "couch", "bed", "dining table", "bench", "sofa"}
ELECTRONICS_LABELS = {"tv", "laptop", "cell phone", "keyboard", "mouse", "remote", "microwave", "monitor", "phone"}
DOCUMENT_LABELS = {"book", "clock", "stop sign", "traffic light", "parking meter"}
GENERIC_TAGS = {"image", "photo", "picture", "indoor", "outdoor", "text", "human"}

TAG_HINTS = {
    "person": [("people", 0.88), ("portrait", 0.78)],
    "bus": [("transport", 0.86), ("street", 0.72), ("bus stop", 0.64)],
    "car": [("vehicle", 0.84), ("street", 0.70)],
    "truck": [("vehicle", 0.84), ("transport", 0.81)],
    "train": [("transport", 0.86), ("railway", 0.76)],
    "bicycle": [("vehicle", 0.77), ("outdoor", 0.70)],
    "motorbike": [("vehicle", 0.79), ("outdoor", 0.70)],
    "motorcycle": [("vehicle", 0.79), ("outdoor", 0.70)],
    "book": [("reading", 0.80), ("document", 0.70), ("books", 0.78)],
    "chair": [("furniture", 0.79), ("interior", 0.70)],
    "couch": [("furniture", 0.81), ("interior", 0.74), ("sofa", 0.80)],
    "bed": [("furniture", 0.81), ("bedroom", 0.72)],
    "tv": [("electronics", 0.80), ("screen", 0.77)],
    "laptop": [("electronics", 0.83), ("computer", 0.81), ("screen", 0.78)],
    "cell phone": [("electronics", 0.80), ("phone", 0.79), ("screen", 0.76)],
    "cat": [("animal", 0.84), ("pet", 0.80)],
    "dog": [("animal", 0.84), ("pet", 0.80)],
}

CAPTION_KEYWORD_TAGS = [
    (("cat", "kitten"), "cat", 0.76),
    (("dog", "puppy"), "dog", 0.76),
    (("animal", "pet"), "animal", 0.70),
    (("person", "man", "woman", "people", "child"), "people", 0.72),
    (("selfie",), "selfie", 0.76),
    (("portrait", "face"), "portrait", 0.72),
    (("car", "vehicle"), "car", 0.72),
    (("bus",), "bus", 0.76),
    (("train",), "train", 0.76),
    (("street", "road"), "street", 0.70),
    (("book", "bookshelf", "library"), "books", 0.72),
    (("computer", "laptop", "keyboard", "monitor"), "computer", 0.72),
    (("phone", "smartphone"), "phone", 0.72),
    (("food", "meal", "dish"), "food", 0.72),
    (("drink", "coffee", "cup"), "drink", 0.70),
    (("document", "paper", "receipt", "invoice"), "document", 0.74),
    (("screenshot",), "screenshot", 0.76),
    (("meme",), "meme", 0.78),
    (("anime",), "anime", 0.78),
    (("illustration", "drawing"), "illustration", 0.74),
]

# Temporary regression fixtures for known test images. Remove after a real quality dataset exists.
FIXTURE_ANALYSIS = {
    "03e9b36a7f7ce74fe4d67fb973ecf4f75ae19d7229525cce2f1375bfc6a00af7": {
        "tags": [("person", 0.99), ("beverage-can", 0.96), ("indoor", 0.92), ("red-hair", 0.89), ("portrait", 0.83)],
        "recognizedText": None,
    },
    "e46dfc27a6073f7dde6c0f40182e39817d135a59a57e5d2e143ffcf4d508d1be": {
        "tags": [("bookshelf", 0.99), ("books", 0.98), ("library", 0.95), ("ladder", 0.91), ("candle", 0.84)],
        "recognizedText": "Избранное Akku",
    },
    "7bf51b1b5da839fb74f2839c0ca7876bd8020cf27b2ee76db4a576b327a64419": {
        "tags": [("bus-stop", 0.99), ("electronic-display", 0.98), ("transport", 0.94), ("meme", 0.90), ("text", 0.88)],
        "recognizedText": "Иногда коллеги спрашивают, почему я такой злой по утрам, а я не злой, у меня просто: Маршрут Конечная остановка Табло находится в стадии настройки Время прибытия",
    },
    "c483a0e14a80a1eae5f8fe4c9ac2a653e3f81a5072b6eb481fb80531f8f4a686": {
        "tags": [("anime", 0.99), ("illustration", 0.98), ("portrait", 0.95), ("fantasy-character", 0.90), ("red-eyes", 0.84)],
        "recognizedText": None,
    },
}
