class SQLAlchemyError(Exception): pass
class IntegrityError(SQLAlchemyError): pass
class NoResultFound(SQLAlchemyError): pass
class OperationalError(SQLAlchemyError): pass
