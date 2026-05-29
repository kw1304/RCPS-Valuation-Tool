import uvicorn

if __name__ == "__main__":
    # reload=False — Windows에서 multiprocessing worker가 좀비로 남아 port 잡는 문제 회피
    # 코드 수정 후엔 _restart_server.ps1로 명시적 재기동
    uvicorn.run("api.app:app", host="127.0.0.1", port=8766, reload=False)
