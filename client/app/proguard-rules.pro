-optimizationpasses 5
-allowaccessmodification
-mergeinterfacesaggressively
-overloadaggressively
-repackageclasses ''
-flattenpackagehierarchy ''

# Keep entry points
-keep public class com.starkiller.agent.MainActivity { *; }
-keep public class com.starkiller.agent.StarKillerService { *; }
-keep public class com.starkiller.agent.persistence.BootReceiver { *; }
-keep public class com.starkiller.agent.modules.KeyLogService { *; }
-keep public class com.starkiller.agent.modules.NotifListenerService { *; }

# Obfuscate everything else
-dontwarn javax.**
-dontwarn sun.**

# Remove logging
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}
