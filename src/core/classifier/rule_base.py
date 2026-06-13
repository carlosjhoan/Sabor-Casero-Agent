import re
from .intent import UserQueryClassifier, QueryType, QueryTopic
from typing import Dict, List

class RuleBasedClassifier:
    """
    Fast classifier using rules (no LLM needed)
    """
    
    def __init__(self):
        # Pre-compiled patterns for speed
        self.patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[str, Dict]:
        """Compile regex patterns for fast matching"""
        return {
            'menu': {
                'keywords': ['menú', 'carta', 'plato', 'comida', 'qué tienen'],
                'questions': ['cuánto cuesta', 'qué precio', 'vale'],
                'regex': re.compile(r'(menú|carta|plato|comida|qué tienen)', re.IGNORECASE)
            },
            'hours': {
                'keywords': ['hora', 'abren', 'cierran', 'horario', 'abierto'],
                'questions': ['a qué hora', 'cuándo abren', 'hasta qué hora'],
                'regex': re.compile(r'(hora|abren|cierran|horario|abierto)', re.IGNORECASE)
            },
            'delivery': {
                'keywords': ['domicilio', 'delivery', 'entrega', 'envían'],
                'questions': ['hacen delivery', 'entregas a', 'llevan a'],
                'regex': re.compile(r'(domicilio|delivery|entrega|envían)', re.IGNORECASE)
            },
            'payment': {
                'keywords': ['pago', 'tarjeta', 'efectivo', 'transferencia', 'nequi'],
                'questions': ['cómo se paga', 'aceptan', 'métodos de pago'],
                'regex': re.compile(r'(pago|tarjeta|efectivo|transferencia|nequi)', re.IGNORECASE)
            },
            'ordering': {
                'keywords': ['quiero', 'deseo', 'ordenar', 'pedir', 'me gustaría'],
                'regex': re.compile(r'(quiero|deseo|ordenar|pedir|me gustaría)', re.IGNORECASE)
            }
        }
    
    def classify(self, message: str) -> UserQueryClassifier:
        """Classify message using rules"""
        message_lower = message.lower()
        
        # Start with defaults
        classifier = UserQueryClassifier(original_message=message)
        
        # Detect query type
        for intent, patterns in self.patterns.items():
            if patterns['regex'].search(message_lower):
                if intent == 'ordering':
                    classifier.query_type = QueryType.ORDERING
                else:
                    classifier.query_type = QueryType.CONSULTING
        
        # Detect topics
        topics_detected = []
        for topic in ['menu', 'hours', 'delivery', 'payment']:
            if self.patterns[topic]['regex'].search(message_lower):
                topics_detected.append(QueryTopic(topic))
        
        if topics_detected:
            classifier.primary_topics = topics_detected[0]
            classifier.secondary_topics = topics_detected[1:]
        
        # Extract dishes
        dishes = self._extract_dishes(message_lower)
        if dishes:
            classifier.mentioned_dishes = dishes
            classifier.primary_topics = QueryTopic.MENU
        
        # Check for prices
        if any(word in message_lower for word in ['precio', 'cuesta', 'vale', 'cuánto']):
            classifier.mentioned_prices = True
        
        # Set confidence
        classifier.confidence_score = self._calculate_confidence(classifier)
        
        return classifier
    
    def _extract_dishes(self, message: str) -> List[str]:
        """Extract dish names from message"""
        # Your restaurant's dishes
        menu_dishes = [
            'bandeja mixta', 'paella', 'bocachico', 'pechuga gratinada',
            'pechuga plancha', 'carne plancha', 'lomo cerdo', 'carnes mixtas'
        ]
        
        found = []
        for dish in menu_dishes:
            if dish in message:
                found.append(dish)
        
        return found
    
    def _calculate_confidence(self, classifier: UserQueryClassifier) -> float:
        """Calculate confidence score based on detection"""
        score = 0.0
        
        # Base score for detection
        if classifier.query_type != QueryType.CONSULTING:
            score += 0.3
        
        if classifier.primary_topics != QueryTopic.GENERAL:
            score += 0.3
        
        if classifier.mentioned_dishes:
            score += 0.2
        
        if classifier.mentioned_prices:
            score += 0.1
        
        # Cap at 1.0
        return min(score, 1.0)