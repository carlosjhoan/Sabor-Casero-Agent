from typing import List, Optional
from src.core.classifier.intent import Detail, QueryType, QueryTopic
from src.utils.utils import print_section


class InfoResponseBuilder:
    """
    Construye respuestas enfocadas en información solicitada por el cliente.
    Maneja: CONSULTING para todos los topics (MENU, DELIVERY, PAYMENT, etc.)
    """

    NO_RAG_TOPICS = {QueryTopic.GREETING, QueryTopic.FAREWELL, QueryTopic.UNKNOWN}

    def process(
        self,
        info_segments: List[Detail],
        extracted_info: Optional[str] = None
    ) -> str:
        """
        Genera mensaje de respuesta basado en información consultada.

        Args:
            info_segments: Segmentos clasificados como CONSULTING
            extracted_info: Información adicional del RAG (opcional)

        Returns:
            Mensaje de respuesta informativo
        """
        if not info_segments:
            return ""

        print_section(
            head="📚 InfoResponseBuilder procesando",
            msg=f"Segmentos: {len(info_segments)}",
            symbol="🔄"
        )

        valid_segments = [
            seg for seg in info_segments 
            if seg.topic not in self.NO_RAG_TOPICS
        ]

        if not valid_segments:
            return ""

        response_parts = []

        for segment in valid_segments:
            segment_response = self._build_segment_response(segment)
            if segment_response:
                response_parts.append(segment_response)

        if not response_parts:
            return ""

        return " | ".join(response_parts)

    def _build_segment_response(self, segment: Detail) -> str:
        """Construye respuesta para un segmento específico"""
        
        if segment.info_extracted and segment.info_extracted != "No hay información por el momento":
            return segment.info_extracted
        
        return self._build_fallback_response(segment.topic, segment.focus)

    def _build_fallback_response(self, topic: QueryTopic, focus: str) -> str:
        """Construye respuesta cuando no hay info del RAG - SIN hallucination"""
        return f"[INFO_NO_DISPONIBLE: topic={topic.value}, focus={focus}]"

    def is_consulting_segment(self, segment: Detail) -> bool:
        """Verifica si un segmento es de tipo CONSULTING"""
        return segment.query_type == QueryType.CONSULTING

    def filter_consulting_segments(self, segments: List[Detail]) -> List[Detail]:
        """Filtra solo los segmentos de tipo CONSULTING"""
        return [seg for seg in segments if self.is_consulting_segment(seg)]