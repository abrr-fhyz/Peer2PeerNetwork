## Configure Port and IP settings through environment variables
If using default HOST_PORT values, it may cause issues if another device within the system is using the same configuration.
Make sure API_PORT and DHT_PORT are the same for all peers, otherwise peer discovery won't function.

## Install Requirements
```bash
    pip install -r requirements.txt
```

## Initiate Streaming Server Backend:
```bash
    python streaming_server.py
```
Only one instance required per network.

## Start StreamLit Server
```bash
    streamlit run main.py
```
Create as many instances as existing peers.
