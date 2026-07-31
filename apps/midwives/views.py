from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Hospital, MidwifeProfile, Qualification, Certificate, Expertise, SavedMidwife
from .serializers import (
    HospitalSerializer,
    MidwifeProfileSerializer,
    QualificationSerializer,
    CertificateSerializer,
    ExpertiseSerializer,
    SavedMidwifeSerializer
)


class HospitalViewSet(viewsets.ModelViewSet):
    queryset = Hospital.objects.all()
    serializer_class = HospitalSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class MidwifeProfileViewSet(viewsets.ModelViewSet):
    queryset = MidwifeProfile.objects.all()
    serializer_class = MidwifeProfileSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(verification_status=status_param)
        return queryset

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def verify(self, request, pk=None):
        midwife = self.get_object()
        action_type = request.data.get('action')  # APPROVE or REJECT
        if action_type == 'APPROVE':
            midwife.verification_status = MidwifeProfile.VerificationStatus.APPROVED
            midwife.verified_by = request.user
            midwife.save()
            return Response({'status': 'Midwife verified successfully'})
        elif action_type == 'REJECT':
            midwife.verification_status = MidwifeProfile.VerificationStatus.REJECTED
            midwife.rejection_reason = request.data.get('reason', '')
            midwife.save()
            return Response({'status': 'Midwife verification rejected'})
        return Response({'error': 'Invalid action. Use APPROVE or REJECT.'}, status=status.HTTP_400_BAD_REQUEST)


class SavedMidwifeViewSet(viewsets.ModelViewSet):
    serializer_class = SavedMidwifeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SavedMidwife.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
