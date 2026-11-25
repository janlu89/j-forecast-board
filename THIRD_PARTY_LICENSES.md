# Third-party software

## Included in this repository

| Component | Version | File | Licence | Notes |
|---|---|---|---|---|
| plotly.js | 4.1.1 | `src/j_forecast_board/static/vendor/plotly.min.js` | MIT, Copyright 2012-2026 Plotly, Inc. | unmodified minified build; SHA-256 `3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f` |

## Installed by the setup (not included)

These are downloaded by `pip` from their official sources during setup. Versions are pinned in
`requirements.txt`.

| Package | Version | Licence |
|---|---|---|
| timestral | 1.0.0 (code) | Apache-2.0 |
| torch (CPU build) | 2.15.0 | BSD-3-Clause |
| numpy | 2.5.5 | BSD-3-Clause (and bundled permissive licences) |
| pandas | 3.1.1 | BSD-3-Clause |
| fastapi | 0.165.0 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| pydantic | 2.14.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| python-multipart | 0.0.34 | Apache-2.0 |
| holidays | 0.109 | MIT |
| huggingface-hub | 2.4.0 | Apache-2.0 |
| safetensors | 0.8.0 | Apache-2.0 |

## Downloaded at run time (not included)

| What | Licence | Notes |
|---|---|---|
| Timestral model weights (5M, 28M, 123M, 209M) | Mistral AI "Modified MIT" | Free except for companies (and their employees) with consolidated revenue above 20 M$ per month, which need a commercial licence from Mistral. Downloaded from Hugging Face by the user. |
| Rossmann store sales | Kaggle competition data (2015) | Read from a public GitHub mirror. Check Kaggle's competition rules before any use beyond evaluation. |
| Bike sharing (UCI 275) | CC BY 4.0 | Fanaee-T and Gama (2013). |
| ETTh1 (ETDataset) | CC BY-ND 4.0 | Zhou et al. (2021). |
| Airline passengers | public domain textbook series | Box and Jenkins (1976). |
| Germany electricity (Open Power System Data) | open data | |
| Melbourne daily minimum temperature | Australian Bureau of Meteorology | via the jbrownlee/Datasets repository. |

Two small public datasets (airline passengers, bike sharing) are committed as test fixtures; see
`tests/golden/README.md`.
