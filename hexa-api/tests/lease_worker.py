"""Independent-process lease contender for the opt-in PostgreSQL lane."""
import json
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.tasks.service import TaskExecutor


def main():
    engine = create_engine(os.environ['HEXA_LEASE_TEST_URL'])
    factory = sessionmaker(bind=engine)
    request = json.loads(sys.stdin.readline())
    executor = TaskExecutor(factory, None, lease_owner=request['owner'])
    print('ready', flush=True)
    if sys.stdin.readline().strip() != 'go':
        raise RuntimeError('missing start signal')
    try:
        if request['action'] == 'recover':
            executor.recover()
            result = 'recovered'
        else:
            with factory() as db:
                result = executor.acquire_run_lease(db, request['run_id'])
                db.commit()
        print(json.dumps({'result': result}), flush=True)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
