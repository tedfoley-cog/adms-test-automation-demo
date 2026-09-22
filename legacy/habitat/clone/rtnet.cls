!  rtnet.cls - clone schema for the RTNET application.
!  Lists the databases, tasks and savecases that make up the clone. The clone
!  instance itself is a single .car file created by hdbcloner.

CLONE RTNET

   DATABASES
      SCADAMOM
      NETMOM
   END DATABASES

   TASKS
      RTGENACE      ! reporting ACE and regulation allocation, 4 s cycle
      LOADSHED      ! underfrequency load shedding arming, 2 s cycle
      RTNETSE       ! state estimator, 60 s cycle
   END TASKS

   SAVECASES
      RTNET_EMS_0742
      RTNET_EMS_NEWCASE
   END SAVECASES

END CLONE
