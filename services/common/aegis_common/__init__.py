"""Librería compartida por los microservicios de AegisVolt.

Solo contiene preocupaciones transversales (configuración, logging, flags, helpers de DynamoDB).
La lógica de negocio vive en cada microservicio: cada uno es dueño de su propia tabla
(patrón Database-per-Service).
"""
