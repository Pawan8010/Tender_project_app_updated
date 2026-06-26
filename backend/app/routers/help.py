from fastapi import APIRouter

from app.glossary import GLOSSARY

router = APIRouter()


@router.get("/glossary")
def get_glossary():
    return GLOSSARY
