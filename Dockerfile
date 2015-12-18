FROM python:onbuild

RUN useradd -u 3204 tensor_hurler
USER tensor_hurler

CMD ./hornet_rulers.py
