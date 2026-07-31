from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import models
from django.utils import timezone
from .models import Consultation, ConsultationNote, VoiceSession
from .serializers import (
    ConsultationSerializer,
    ConsultationNoteSerializer,
    VoiceSessionSerializer
)


class ConsultationViewSet(viewsets.ModelViewSet):
    queryset = Consultation.objects.all()
    serializer_class = ConsultationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'midwife_profile'):
            return Consultation.objects.filter(
                models.Q(user=user) | models.Q(midwife=user.midwife_profile)
            )
        return Consultation.objects.filter(user=user)

    def perform_create(self, serializer):
        appointment = serializer.validated_data['appointment']
        serializer.save(
            user=appointment.user,
            midwife=appointment.midwife,
            consultation_type=appointment.appointment_type
        )

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        consultation = self.get_object()
        consultation.status = Consultation.ConsultationStatus.ACTIVE
        consultation.started_at = timezone.now()
        consultation.save()
        return Response({'status': 'Consultation started', 'started_at': consultation.started_at})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        consultation = self.get_object()
        consultation.status = Consultation.ConsultationStatus.COMPLETED
        consultation.ended_at = timezone.now()
        consultation.summary = request.data.get('summary', consultation.summary)
        consultation.diagnosis = request.data.get('diagnosis', consultation.diagnosis)
        consultation.recommendation = request.data.get('recommendation', consultation.recommendation)
        consultation.save()
        return Response({'status': 'Consultation completed', 'ended_at': consultation.ended_at})

    @action(detail=True, methods=['post'])
    def add_note(self, request, pk=None):
        consultation = self.get_object()
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != consultation.midwife:
            return Response(
                {'error': 'Only the assigned midwife can add consultation notes.'},
                status=status.HTTP_403_FORBIDDEN
            )

        note_text = request.data.get('note')
        if not note_text:
            return Response({'error': 'Note content is required.'}, status=status.HTTP_400_BAD_REQUEST)

        note = ConsultationNote.objects.create(
            consultation=consultation,
            midwife=request.user.midwife_profile,
            note=note_text
        )
        serializer = ConsultationNoteSerializer(note)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
