import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
import uvicorn

if __name__ == "__main__":
    uvicorn.run("risk.interface.api.app:app", host="127.0.0.1", port=8533, reload=False)
