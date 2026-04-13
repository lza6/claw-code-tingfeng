import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import jsonschema

logger = logging.getLogger("durable.schema")

class SchemaValidator:
    """Validator for Durable Surfaces using JSON Schema"""
    
    def __init__(self, schemas_dir: Optional[Path] = None):
        if schemas_dir is None:
            # Default to the directory where this file is located
            self.schemas_dir = Path(__file__).parent
        else:
            self.schemas_dir = schemas_dir
            
        self.schemas: Dict[str, dict] = {}
        self._load_schemas()
        
    def _load_schemas(self):
        """Load all JSON schemas from the schemas directory"""
        if not self.schemas_dir.exists():
            logger.warning(f"Schemas directory not found: {self.schemas_dir}")
            return
            
        for schema_file in self.schemas_dir.glob("*.schema.json"):
            try:
                with open(schema_file, "r", encoding="utf-8") as f:
                    schema_id = schema_file.stem.replace(".schema", "")
                    self.schemas[schema_id] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load schema {schema_file}: {e}")
                
    def validate(self, surface_type: str, data: Dict[str, Any]) -> bool:
        """Validate data against the schema for the given surface type"""
        if surface_type not in self.schemas:
            # If no schema exists, we assume it's valid (gradual adoption)
            logger.debug(f"No schema found for {surface_type}, skipping validation")
            return True
            
        try:
            jsonschema.validate(instance=data, schema=self.schemas[surface_type])
            return True
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"Schema validation failed for {surface_type}: {e.message}")
            # Raise exception instead of just returning False so caller knows why
            raise ValueError(f"Invalid {surface_type} data: {e.message}") from e
