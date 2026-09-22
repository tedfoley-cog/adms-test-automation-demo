!  ace_calc.f90 - RTGENACE batch task, 4 second control cycle.
!
!  Computes Reporting ACE for the balancing authority area and allocates the
!  regulation requirement across the units on AGC. Reporting ACE follows the
!  NERC BAL-001 definition:
!
!     ACE = (NI_a - NI_s) - 10B (F_a - F_s) - I_ME
!
!  where B is the frequency bias setting in MW/0.1 Hz (carried as a negative
!  number in BIAS_FREQ, as it is on the platform).
!
!  Off-line entry point: rtgenace <savecase-export-path>
!  On the platform the same computation runs bound to the SCADAMOM clone.

PROGRAM RTGENACE

   USE HAB_SAVECASE
   IMPLICIT NONE

   CHARACTER(LEN=256) :: PATH
   TYPE(SAVECASE)     :: CASE
   REAL               :: ACE, SETPT(MAXUNT)
   INTEGER            :: IERR, I

   CALL GET_COMMAND_ARGUMENT(1, PATH)
   IF (LEN_TRIM(PATH) == 0) THEN
      WRITE(*, '(A)') 'RTGENACE: usage: rtgenace <savecase-export>'
      STOP 2
   END IF

   CALL HDB_READ_EXPORT(TRIM(PATH), CASE, IERR)
   IF (IERR /= 0) THEN
      WRITE(*, '(A,I2)') 'RTGENACE: savecase read failed, ierr=', IERR
      STOP 3
   END IF

   CALL RPTACE(CASE, ACE)
   CALL ALLOCR(CASE, ACE, 4.0, SETPT)

   WRITE(*, '(A,A)')      'SAVECASE ', TRIM(CASE%NAME)
   WRITE(*, '(A,F12.4)')  'ACE_MW   ', ACE
   DO I = 1, CASE%NUNT
      WRITE(*, '(A,A20,F12.4)') 'SETPT    ', CASE%UNT(I)%ID_UNIT, SETPT(I)
   END DO

CONTAINS

   SUBROUTINE RPTACE(CASE, ACE)
      TYPE(SAVECASE), INTENT(IN)  :: CASE
      REAL,           INTENT(OUT) :: ACE

      REAL    :: ANIA, ANIS, DF, BIASMW
      INTEGER :: I

      ANIA = 0.0
      ANIS = 0.0
      DO I = 1, CASE%NTIE
         ANIA = ANIA + CASE%TIE(I)%ACTUAL_TIELINE
         ANIS = ANIS + CASE%TIE(I)%SCHED_TIELINE
      END DO

      DF     = CASE%FREQ%VALUE_FREQ - CASE%FREQ%SCHED_FREQ
      BIASMW = 10.0 * CASE%FREQ%BIAS_FREQ * DF

      ACE = (ANIA - ANIS) - BIASMW - CASE%VALUE_METERR
   END SUBROUTINE RPTACE

   SUBROUTINE ALLOCR(CASE, ACE, CYCSEC, SETPT)
      TYPE(SAVECASE), INTENT(IN)  :: CASE
      REAL,           INTENT(IN)  :: ACE
      REAL,           INTENT(IN)  :: CYCSEC
      REAL,           INTENT(OUT) :: SETPT(MAXUNT)

      REAL, PARAMETER :: DEADBD = 5.0
      REAL    :: TOTPF, CORR, SHARE, RAMPLM, TARGET
      INTEGER :: I

      DO I = 1, MAXUNT
         SETPT(I) = 0.0
      END DO

      IF (ABS(ACE) <= DEADBD) RETURN

      TOTPF = 0.0
      DO I = 1, CASE%NUNT
         IF (CASE%UNT(I)%AGC_UNIT .AND. CASE%UNT(I)%PARTF_UNIT > 0.0) THEN
            TOTPF = TOTPF + CASE%UNT(I)%PARTF_UNIT
         END IF
      END DO
      IF (TOTPF <= 0.0) RETURN

      CORR = -ACE
      DO I = 1, CASE%NUNT
         IF (.NOT. CASE%UNT(I)%AGC_UNIT) CYCLE
         IF (CASE%UNT(I)%PARTF_UNIT <= 0.0) CYCLE

         SHARE  = CORR * (CASE%UNT(I)%PARTF_UNIT / TOTPF)
         RAMPLM = CASE%UNT(I)%RAMP_UNIT * (CYCSEC / 60.0)
         IF (SHARE >  RAMPLM) SHARE =  RAMPLM
         IF (SHARE < -RAMPLM) SHARE = -RAMPLM

         TARGET = CASE%UNT(I)%MW_UNIT + SHARE
         IF (TARGET < CASE%UNT(I)%MIN_UNIT) TARGET = CASE%UNT(I)%MIN_UNIT
         IF (TARGET > CASE%UNT(I)%MAX_UNIT) TARGET = CASE%UNT(I)%MAX_UNIT

         SETPT(I) = TARGET - CASE%UNT(I)%MW_UNIT
      END DO
   END SUBROUTINE ALLOCR

END PROGRAM RTGENACE
