-optimizationpasses 5
-allowaccessmodification
-mergeinterfacesaggressively
-overloadaggressively
-repackageclasses ''
-flattenpackagehierarchy ''

# Strip source filenames from stack traces
-renamesourcefileattribute ''

# Keep ONLY manifest-declared components (fully qualified)
-keep public class com.georgetech.filesync.MainActivity { *; }
-keep public class com.georgetech.filesync.SyncService { *; }
-keep public class com.georgetech.filesync.GrantActivity { *; }

# Obfuscate everything else
-dontwarn javax.**
-dontwarn sun.**
-dontwarn kotlin.**
-dontwarn kotlinx.**

# Remove all logging
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}

# Remove Kotlin null checks (they leak parameter names)
-assumenosideeffects class kotlin.jvm.internal.Intrinsics {
    public static void checkNotNullParameter(...);
    public static void checkNotNullExpressionValue(...);
    public static void checkNotNull(...);
}

# Adapt string constants that reference class names
-adaptclassstrings
-adaptresourcefilenames
-adaptresourcefilecontents
