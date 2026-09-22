!  hab_savecase.f90
!
!  Reader for the ASCII savecase exports produced by hdbexport for the
!  RTNET.EMS clone. On the production platform the batch tasks bind directly
!  to the memory-resident HDB records through the generated INCLUDE files;
!  off-line replay uses the same record layout read from the export file so
!  that a savecase can be re-run without a clone context.

MODULE HAB_SAVECASE

   IMPLICIT NONE

   INTEGER, PARAMETER :: MAXTIE = 32
   INTEGER, PARAMETER :: MAXUNT = 64
   INTEGER, PARAMETER :: MAXFDR = 256

   TYPE :: FREQ_REC
      CHARACTER(LEN=20) :: ID_FREQ    = ' '
      REAL              :: VALUE_FREQ = 60.0
      REAL              :: SCHED_FREQ = 60.0
      REAL              :: BIAS_FREQ  = 0.0
      CHARACTER(LEN=1)  :: QUAL_FREQ  = 'N'
   END TYPE FREQ_REC

   TYPE :: TIE_REC
      CHARACTER(LEN=20) :: ID_TIELINE     = ' '
      REAL              :: ACTUAL_TIELINE = 0.0
      REAL              :: SCHED_TIELINE  = 0.0
      CHARACTER(LEN=1)  :: QUAL_TIELINE   = 'N'
   END TYPE TIE_REC

   TYPE :: UNIT_REC
      CHARACTER(LEN=20) :: ID_UNIT    = ' '
      REAL              :: MW_UNIT    = 0.0
      REAL              :: MIN_UNIT   = 0.0
      REAL              :: MAX_UNIT   = 0.0
      REAL              :: RAMP_UNIT  = 0.0
      REAL              :: PARTF_UNIT = 0.0
      LOGICAL           :: AGC_UNIT   = .FALSE.
   END TYPE UNIT_REC

   TYPE :: FDR_REC
      CHARACTER(LEN=20) :: ID_FEEDER    = ' '
      REAL              :: LOAD_FEEDER  = 0.0
      INTEGER           :: BLOCK_FEEDER = 0
      INTEGER           :: PRIO_FEEDER  = 0
   END TYPE FDR_REC

   TYPE :: SAVECASE
      CHARACTER(LEN=32) :: NAME = ' '
      TYPE(FREQ_REC)    :: FREQ
      REAL              :: VALUE_METERR = 0.0
      INTEGER           :: NTIE = 0
      INTEGER           :: NUNT = 0
      INTEGER           :: NFDR = 0
      TYPE(TIE_REC)     :: TIE(MAXTIE)
      TYPE(UNIT_REC)    :: UNT(MAXUNT)
      TYPE(FDR_REC)     :: FDR(MAXFDR)
   END TYPE SAVECASE

CONTAINS

   SUBROUTINE HDB_READ_EXPORT(PATH, CASE, IERR)
      CHARACTER(LEN=*), INTENT(IN)  :: PATH
      TYPE(SAVECASE),   INTENT(OUT) :: CASE
      INTEGER,          INTENT(OUT) :: IERR

      CHARACTER(LEN=256) :: LINE
      CHARACTER(LEN=20)  :: REC
      CHARACTER(LEN=1)   :: QUAL
      INTEGER            :: LUN, IOS
      REAL               :: A, B, C, D, E

      LUN  = 21
      REC  = ' '
      IERR = 0

      OPEN(UNIT=LUN, FILE=PATH, STATUS='OLD', ACTION='READ', IOSTAT=IOS)
      IF (IOS /= 0) THEN
         IERR = 1
         RETURN
      END IF

10    CONTINUE
      READ(LUN, '(A)', IOSTAT=IOS) LINE
      IF (IOS /= 0) GO TO 90
      IF (LEN_TRIM(LINE) == 0) GO TO 10
      IF (LINE(1:1) == '*') GO TO 10

      IF (INDEX(LINE, 'SAVECASE ') == 1) THEN
         CASE%NAME = ADJUSTL(LINE(10:))
         GO TO 10
      END IF
      IF (INDEX(LINE, 'RECORD ') == 1) THEN
         REC = ADJUSTL(LINE(8:))
         GO TO 10
      END IF
      IF (INDEX(LINE, 'END') == 1) GO TO 90
      IF (INDEX(LINE, 'CLONE') == 1 .OR. INDEX(LINE, 'TIMESTAMP') == 1) GO TO 10

      SELECT CASE (TRIM(REC))

      CASE ('FREQ')
         READ(LINE, *, IOSTAT=IOS) CASE%FREQ%ID_FREQ, A, B, C, QUAL
         IF (IOS /= 0) GO TO 80
         CASE%FREQ%VALUE_FREQ = A
         CASE%FREQ%SCHED_FREQ = B
         CASE%FREQ%BIAS_FREQ  = C
         CASE%FREQ%QUAL_FREQ  = QUAL

      CASE ('TIELINE')
         IF (CASE%NTIE >= MAXTIE) GO TO 80
         CASE%NTIE = CASE%NTIE + 1
         READ(LINE, *, IOSTAT=IOS) CASE%TIE(CASE%NTIE)%ID_TIELINE, A, B, QUAL
         IF (IOS /= 0) GO TO 80
         CASE%TIE(CASE%NTIE)%ACTUAL_TIELINE = A
         CASE%TIE(CASE%NTIE)%SCHED_TIELINE  = B
         CASE%TIE(CASE%NTIE)%QUAL_TIELINE   = QUAL

      CASE ('METERR')
         READ(LINE, *, IOSTAT=IOS) REC, A
         IF (IOS /= 0) GO TO 80
         CASE%VALUE_METERR = A
         REC = 'METERR'

      CASE ('UNIT')
         IF (CASE%NUNT >= MAXUNT) GO TO 80
         CASE%NUNT = CASE%NUNT + 1
         READ(LINE, *, IOSTAT=IOS) CASE%UNT(CASE%NUNT)%ID_UNIT, A, B, C, D, E, QUAL
         IF (IOS /= 0) GO TO 80
         CASE%UNT(CASE%NUNT)%MW_UNIT    = A
         CASE%UNT(CASE%NUNT)%MIN_UNIT   = B
         CASE%UNT(CASE%NUNT)%MAX_UNIT   = C
         CASE%UNT(CASE%NUNT)%RAMP_UNIT  = D
         CASE%UNT(CASE%NUNT)%PARTF_UNIT = E
         CASE%UNT(CASE%NUNT)%AGC_UNIT   = (QUAL == 'T')

      CASE ('FEEDER')
         IF (CASE%NFDR >= MAXFDR) GO TO 80
         CASE%NFDR = CASE%NFDR + 1
         READ(LINE, *, IOSTAT=IOS) CASE%FDR(CASE%NFDR)%ID_FEEDER, A, &
                                   CASE%FDR(CASE%NFDR)%BLOCK_FEEDER, &
                                   CASE%FDR(CASE%NFDR)%PRIO_FEEDER
         IF (IOS /= 0) GO TO 80
         CASE%FDR(CASE%NFDR)%LOAD_FEEDER = A

      CASE DEFAULT
         CONTINUE

      END SELECT
      GO TO 10

80    CONTINUE
      IERR = 2
      CLOSE(LUN)
      RETURN

90    CONTINUE
      CLOSE(LUN)
      RETURN
   END SUBROUTINE HDB_READ_EXPORT

END MODULE HAB_SAVECASE
