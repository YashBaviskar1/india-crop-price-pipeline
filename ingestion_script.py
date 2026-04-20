import requests
import pandas as pd
from io import StringIO

API_KEY = "579b464db66ec23bdd000001561116a24549411d4f78cb8c203be4ce"

BASE_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"

params = {
    "api-key": API_KEY,
    "format": "csv",
    "limit": 1000,   # NEVER use 'all'
    "offset": 0
}

response = requests.get(BASE_URL, params=params)

print("Status Code:", response.status_code)

if response.status_code == 200:
    # Convert CSV string → DataFrame
    df = pd.read_csv(StringIO(response.text))

    print("\n✅ Data fetched successfully!")
    print("Shape:", df.shape)

    print("\nColumns:")
    print(df.columns.tolist())

    print("\nSample Data:")
    print(df.head())

else:
    print("❌ Failed to fetch data")
    print(response.text)
