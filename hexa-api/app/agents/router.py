from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.db.models import AgentTemplate


class AgentTemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=2000)
    base: str = Field(min_length=1, max_length=255)
    default_model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default='', max_length=20000)

    @field_validator('name', 'base', 'default_model')
    @classmethod
    def non_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('required')
        return value


def template_json(row):
    return {field: getattr(row, field) for field in ('id', 'name', 'description', 'base', 'default_model', 'system_prompt')} | {'source': 'custom', 'available': True}


def build_agent_router(app, require_session, user_id):
    router = APIRouter(prefix='/api/hexa/agent-templates')

    def storage_unavailable():
        return HTTPException(503, 'Agent 模板存储尚未就绪，请重启应用或执行数据库迁移。')

    def owned(db, template_id, uid):
        row = db.scalar(select(AgentTemplate).where(AgentTemplate.id == template_id, AgentTemplate.user_id == uid))
        if row is None:
            raise HTTPException(404, 'Agent 模板不存在。')
        return row

    @router.get('')
    async def templates(session=Depends(require_session)):
        try:
            with app.state.session_factory() as db:
                rows = db.scalars(select(AgentTemplate).where(AgentTemplate.user_id == user_id(session)).order_by(AgentTemplate.id.desc())).all()
                return {'templates': [template_json(row) for row in rows]}
        except (OperationalError, ProgrammingError):
            raise storage_unavailable() from None

    @router.get('/gateway')
    async def gateway_templates(session=Depends(require_session)):
        try:
            return {'templates': await app.state.gateway.list_agent_templates()}
        except Exception:
            raise HTTPException(502, 'Gateway 模板暂时无法读取，请重试。') from None

    @router.post('', status_code=201)
    async def create(body: AgentTemplateBody, session=Depends(require_session)):
        try:
            with app.state.session_factory() as db:
                row = AgentTemplate(user_id=user_id(session), **body.model_dump())
                db.add(row)
                db.commit()
                return template_json(row)
        except (OperationalError, ProgrammingError):
            raise storage_unavailable() from None

    @router.put('/{template_id}')
    async def update(template_id: int, body: AgentTemplateBody, session=Depends(require_session)):
        try:
            with app.state.session_factory() as db:
                row = owned(db, template_id, user_id(session))
                for field, value in body.model_dump().items():
                    setattr(row, field, value)
                db.commit()
                return template_json(row)
        except (OperationalError, ProgrammingError):
            raise storage_unavailable() from None

    @router.delete('/{template_id}', status_code=204)
    async def remove(template_id: int, session=Depends(require_session)):
        try:
            with app.state.session_factory() as db:
                row = owned(db, template_id, user_id(session))
                db.delete(row)
                db.commit()
        except (OperationalError, ProgrammingError):
            raise storage_unavailable() from None
        return Response(status_code=204)

    return router
