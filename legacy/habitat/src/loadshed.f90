!  loadshed.f90 - LOADSHED batch task, 2 second cycle.
!
!  Arms and evaluates the underfrequency load shedding (UFLS) blocks for the
!  area. Block pickup frequencies follow the usual three-stage arrangement
!  used on distribution feeders; feeders carrying critical load (PRIO_FEEDER
!  equal to 1) are excluded from automatic shedding and are only listed as
!  manual-drop candidates.
!
!  This task has no counterpart in the modern services yet - it is the next
!  migration target. Off-line entry point: loadshed <savecase-export-path>

PROGRAM LOADSHED

   USE HAB_SAVECASE
   IMPLICIT NONE

   REAL, PARAMETER :: FPKUP(3) = (/ 59.30, 59.00, 58.70 /)
   REAL, PARAMETER :: FRESET   = 59.85

   CHARACTER(LEN=256) :: PATH
   TYPE(SAVECASE)     :: CASE
   REAL               :: SHEDMW, MANMW
   INTEGER            :: IERR, I, IBLK, NSHED

   CALL GET_COMMAND_ARGUMENT(1, PATH)
   IF (LEN_TRIM(PATH) == 0) THEN
      WRITE(*, '(A)') 'LOADSHED: usage: loadshed <savecase-export>'
      STOP 2
   END IF

   CALL HDB_READ_EXPORT(TRIM(PATH), CASE, IERR)
   IF (IERR /= 0) THEN
      WRITE(*, '(A,I2)') 'LOADSHED: savecase read failed, ierr=', IERR
      STOP 3
   END IF

   IBLK = 0
   DO I = 1, 3
      IF (CASE%FREQ%VALUE_FREQ <= FPKUP(I)) IBLK = I
   END DO

   SHEDMW = 0.0
   MANMW  = 0.0
   NSHED  = 0

   IF (CASE%FREQ%QUAL_FREQ /= 'N') THEN
      WRITE(*, '(A)') 'LOADSHED: frequency quality not normal, shedding inhibited'
      IBLK = 0
   END IF

   DO I = 1, CASE%NFDR
      IF (CASE%FDR(I)%PRIO_FEEDER == 1) THEN
         MANMW = MANMW + CASE%FDR(I)%LOAD_FEEDER
         CYCLE
      END IF
      IF (IBLK > 0 .AND. CASE%FDR(I)%BLOCK_FEEDER <= IBLK) THEN
         SHEDMW = SHEDMW + CASE%FDR(I)%LOAD_FEEDER
         NSHED  = NSHED + 1
         WRITE(*, '(A,A20,F10.3)') 'TRIP     ', CASE%FDR(I)%ID_FEEDER, &
                                   CASE%FDR(I)%LOAD_FEEDER
      END IF
   END DO

   WRITE(*, '(A,A)')      'SAVECASE ', TRIM(CASE%NAME)
   WRITE(*, '(A,F10.3)')  'FREQ_HZ  ', CASE%FREQ%VALUE_FREQ
   WRITE(*, '(A,I4)')     'BLOCK    ', IBLK
   WRITE(*, '(A,I4)')     'NFEEDER  ', NSHED
   WRITE(*, '(A,F10.3)')  'SHED_MW  ', SHEDMW
   WRITE(*, '(A,F10.3)')  'MANUAL_MW', MANMW
   WRITE(*, '(A,F10.3)')  'RESET_HZ ', FRESET

END PROGRAM LOADSHED
