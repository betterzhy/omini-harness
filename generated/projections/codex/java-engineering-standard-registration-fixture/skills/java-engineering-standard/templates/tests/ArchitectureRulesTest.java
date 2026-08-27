package __BASE_PACKAGE__.architecture;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes;

import com.tngtech.archunit.core.domain.Dependency;
import com.tngtech.archunit.core.domain.JavaClass;
import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchCondition;
import com.tngtech.archunit.lang.ArchRule;
import com.tngtech.archunit.lang.ConditionEvents;
import com.tngtech.archunit.lang.SimpleConditionEvent;
import java.lang.module.ModuleFinder;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

// 复制后必须替换所有 __UPPER_SNAKE_CASE__，并从 module-boundaries.yaml 逐项生成本清单。
@AnalyzeClasses(
    packages = ArchitectureRulesTest.BASE_PACKAGE,
    importOptions = ImportOption.DoNotIncludeTests.class)
class ArchitectureRulesTest {

  static final String BASE_PACKAGE = "__BASE_PACKAGE__";

  private static final String NO_OWNER = "none";
  private static final String CONTRACT = "contract";
  private static final String DOMAIN = "domain";
  private static final String APPLICATION = "application";
  private static final String ADAPTER_IN = "adapter-in";
  private static final String ADAPTER_OUT = "adapter-out";
  private static final String RUNTIME = "runtime";
  private static final String TECHNICAL_SUPPORT = "technical-support";
  private static final String TEST_SUPPORT = "test-support";

  private static final Map<String, ModuleBoundary> MODULES =
      Map.ofEntries(
          Map.entry(
              "__MODULE_A__-contract",
              new ModuleBoundary(
                  "__MODULE_A__",
                  CONTRACT,
                  BASE_PACKAGE + ".__MODULE_A__.contract",
                  Set.of(),
                  Set.of(BASE_PACKAGE + ".__MODULE_A__.contract"),
                  Set.of(),
                  Set.of())),
          Map.entry(
              "__MODULE_A__-domain",
              new ModuleBoundary(
                  "__MODULE_A__",
                  DOMAIN,
                  BASE_PACKAGE + ".__MODULE_A__.domain",
                  Set.of(),
                  Set.of(),
                  Set.of(),
                  Set.of())),
          Map.entry(
              "__MODULE_A__-application",
              new ModuleBoundary(
                  "__MODULE_A__",
                  APPLICATION,
                  BASE_PACKAGE + ".__MODULE_A__.application",
                  Set.of(
                      "__MODULE_A__-contract",
                      "__MODULE_A__-domain",
                      "__MODULE_B__-contract"),
                  Set.of(),
                  Set.of("__RUNTIME_MODULE__"),
                  Set.of())),
          Map.entry(
              "__MODULE_A__-adapter-in",
              new ModuleBoundary(
                  "__MODULE_A__",
                  ADAPTER_IN,
                  BASE_PACKAGE + ".__MODULE_A__.adapter.in",
                  Set.of("__MODULE_A__-contract", "__MODULE_A__-application"),
                  Set.of(),
                  Set.of("__RUNTIME_MODULE__"),
                  Set.of())),
          Map.entry(
              "__MODULE_A__-adapter-out",
              new ModuleBoundary(
                  "__MODULE_A__",
                  ADAPTER_OUT,
                  BASE_PACKAGE + ".__MODULE_A__.adapter.out",
                  Set.of(
                      "__MODULE_A__-contract",
                      "__MODULE_A__-application",
                      "__MODULE_B__-contract"),
                  Set.of(),
                  Set.of("__RUNTIME_MODULE__"),
                  Set.of())),
          Map.entry(
              "__MODULE_B__-contract",
              new ModuleBoundary(
                  "__MODULE_B__",
                  CONTRACT,
                  BASE_PACKAGE + ".__MODULE_B__.contract",
                  Set.of(),
                  Set.of(BASE_PACKAGE + ".__MODULE_B__.contract"),
                  Set.of(),
                  Set.of())),
          Map.entry(
              "__RUNTIME_MODULE__",
              new ModuleBoundary(
                  NO_OWNER,
                  RUNTIME,
                  BASE_PACKAGE + ".__RUNTIME_MODULE__",
                  Set.of(
                      "__MODULE_A__-contract",
                      "__MODULE_A__-domain",
                      "__MODULE_A__-application",
                      "__MODULE_A__-adapter-in",
                      "__MODULE_A__-adapter-out",
                      "__MODULE_B__-contract"),
                  Set.of(),
                  Set.of(),
                  Set.of())));

  private static final Set<String> JAVA_SE_API_PACKAGES =
      ModuleFinder.ofSystem().findAll().stream()
          .filter(reference -> reference.descriptor().name().startsWith("java."))
          .flatMap(reference -> reference.descriptor().packages().stream())
          .collect(Collectors.toUnmodifiableSet());

  static {
    validateRegistry();
  }

  @ArchTest
  static final ArchRule registered_modules_must_respect_roles_dependencies_and_public_packages =
      classes()
          .that()
          .resideInAPackage(BASE_PACKAGE + "..")
          .should(respectDeclaredBoundaries());

  @ArchTest
  static final ArchRule owner_modules_must_not_depend_on_runtime =
      classes()
          .that()
          .resideInAPackage(BASE_PACKAGE + "..")
          .should(notDependOnRuntime());

  @ArchTest
  static void declared_module_graph_must_be_acyclic(JavaClasses ignored) {
    Set<String> visited = new HashSet<>();
    Set<String> visiting = new HashSet<>();
    for (String moduleId : MODULES.keySet()) {
      visit(moduleId, visited, visiting);
    }
  }

  private static ArchCondition<JavaClass> respectDeclaredBoundaries() {
    return new ArchCondition<>("遵守显式角色、允许依赖和跨 Owner 公开包") {
      @Override
      public void check(JavaClass source, ConditionEvents events) {
        Map.Entry<String, ModuleBoundary> sourceEntry = boundaryFor(source.getPackageName());
        if (sourceEntry == null) {
          events.add(SimpleConditionEvent.violated(source, "源类未登记到任何模块边界: " + source.getName()));
          return;
        }

        String sourceId = sourceEntry.getKey();
        ModuleBoundary sourceBoundary = sourceEntry.getValue();
        for (Dependency dependency : source.getDirectDependenciesFromSelf()) {
          JavaClass target = dependency.getTargetClass();
          Map.Entry<String, ModuleBoundary> targetEntry = boundaryFor(target.getPackageName());
          if (targetEntry == null) {
            if (containsPackage(BASE_PACKAGE, target.getPackageName())) {
              events.add(
                  SimpleConditionEvent.violated(source, "目标类未登记到任何模块边界: " + target.getName()));
            } else if (isPackageProhibited(sourceBoundary, target.getPackageName())) {
              events.add(SimpleConditionEvent.violated(source, dependency.getDescription()));
            } else if (isJdkOnlyCoreRole(sourceBoundary.role())
                && !isJdkApiPackage(target.getPackageName())) {
              events.add(SimpleConditionEvent.violated(source, dependency.getDescription()));
            }
            continue;
          }

          String targetId = targetEntry.getKey();
          ModuleBoundary targetBoundary = targetEntry.getValue();
          boolean prohibited =
              sourceBoundary.prohibitedModuleIds().contains(targetId)
                  || isPackageProhibited(sourceBoundary, target.getPackageName());
          if (sourceId.equals(targetId)) {
            if (prohibited) {
              events.add(SimpleConditionEvent.violated(source, dependency.getDescription()));
            }
            continue;
          }

          boolean allowed = sourceBoundary.allowedDependencies().contains(targetId);
          boolean crossOwner = !sourceBoundary.ownerId().equals(targetBoundary.ownerId());
          boolean runtimeAssembly = RUNTIME.equals(sourceBoundary.role());
          boolean publicTarget = isExposed(targetBoundary, target.getPackageName());
          boolean roleViolation = !isRoleDependencyAllowed(sourceBoundary, targetBoundary);
          boolean crossOwnerViolation =
              crossOwner
                  && !runtimeAssembly
                  && (!CONTRACT.equals(targetBoundary.role()) || !publicTarget);
          if (!allowed || prohibited || roleViolation || crossOwnerViolation) {
            events.add(SimpleConditionEvent.violated(source, dependency.getDescription()));
          }
        }
      }
    };
  }

  private static ArchCondition<JavaClass> notDependOnRuntime() {
    return new ArchCondition<>("Owner Module 禁止反向依赖 Runtime Assembly") {
      @Override
      public void check(JavaClass source, ConditionEvents events) {
        Map.Entry<String, ModuleBoundary> sourceEntry = boundaryFor(source.getPackageName());
        if (sourceEntry == null || NO_OWNER.equals(sourceEntry.getValue().ownerId())) {
          return;
        }
        for (Dependency dependency : source.getDirectDependenciesFromSelf()) {
          Map.Entry<String, ModuleBoundary> targetEntry =
              boundaryFor(dependency.getTargetClass().getPackageName());
          if (targetEntry != null && RUNTIME.equals(targetEntry.getValue().role())) {
            events.add(SimpleConditionEvent.violated(source, dependency.getDescription()));
          }
        }
      }
    };
  }

  private static Map.Entry<String, ModuleBoundary> boundaryFor(String packageName) {
    Map.Entry<String, ModuleBoundary> match = null;
    for (Map.Entry<String, ModuleBoundary> entry : MODULES.entrySet()) {
      if (containsPackage(entry.getValue().basePackage(), packageName)
          && (match == null
              || entry.getValue().basePackage().length()
                  > match.getValue().basePackage().length())) {
        match = entry;
      }
    }
    return match;
  }

  private static boolean containsPackage(String registeredPackage, String actualPackage) {
    return actualPackage.equals(registeredPackage)
        || actualPackage.startsWith(registeredPackage + ".");
  }

  private static boolean isExposed(ModuleBoundary boundary, String packageName) {
    return boundary.exposedPackages().stream()
        .anyMatch(exposed -> containsPackage(exposed, packageName));
  }

  private static boolean isJdkOnlyCoreRole(String role) {
    return CONTRACT.equals(role) || DOMAIN.equals(role);
  }

  private static boolean isJdkApiPackage(String packageName) {
    return JAVA_SE_API_PACKAGES.contains(packageName);
  }

  private static boolean isPackageProhibited(
      ModuleBoundary boundary, String packageName) {
    return boundary.prohibitedPackages().stream()
        .anyMatch(prohibited -> containsPackage(prohibited, packageName));
  }

  private static boolean isAdapter(String role) {
    return ADAPTER_IN.equals(role) || ADAPTER_OUT.equals(role);
  }

  private static boolean isRoleDependencyAllowed(
      ModuleBoundary source, ModuleBoundary target) {
    boolean sameOwner = source.ownerId().equals(target.ownerId());
    if (CONTRACT.equals(source.role())) {
      return false;
    }
    if (DOMAIN.equals(source.role())) {
      return sameOwner && TECHNICAL_SUPPORT.equals(target.role());
    }
    if (APPLICATION.equals(source.role())) {
      return CONTRACT.equals(target.role())
          || (sameOwner
              && (DOMAIN.equals(target.role()) || TECHNICAL_SUPPORT.equals(target.role())));
    }
    if (isAdapter(source.role())) {
      return CONTRACT.equals(target.role())
          || (sameOwner
              && (APPLICATION.equals(target.role())
                  || DOMAIN.equals(target.role())
                  || TECHNICAL_SUPPORT.equals(target.role())));
    }
    if (RUNTIME.equals(source.role())) {
      return !RUNTIME.equals(target.role()) && !TEST_SUPPORT.equals(target.role());
    }
    if (TECHNICAL_SUPPORT.equals(source.role())) {
      return sameOwner && TECHNICAL_SUPPORT.equals(target.role());
    }
    return TEST_SUPPORT.equals(source.role());
  }

  private static void validateRegistry() {
    if (BASE_PACKAGE.startsWith("__")
        || MODULES.entrySet().stream()
            .anyMatch(
                entry ->
                    entry.getKey().contains("__")
                        || entry.getValue().ownerId().contains("__")
                        || entry.getValue().basePackage().contains("__"))) {
      throw new IllegalStateException("必须用项目真实基础包和 module-boundaries.yaml 替换架构模板变量");
    }

    Set<String> basePackages = new HashSet<>();
    for (Map.Entry<String, ModuleBoundary> entry : MODULES.entrySet()) {
      if (!basePackages.add(entry.getValue().basePackage())) {
        throw new IllegalStateException("模块基础包重复: " + entry.getValue().basePackage());
      }
      for (String dependency : entry.getValue().allowedDependencies()) {
        if (!MODULES.containsKey(dependency)) {
          throw new IllegalStateException(entry.getKey() + " 引用未登记模块 " + dependency);
        }
        if (!isRoleDependencyAllowed(entry.getValue(), MODULES.get(dependency))) {
          throw new IllegalStateException(entry.getKey() + " 存在不允许的角色依赖 " + dependency);
        }
        if (entry.getValue().prohibitedModuleIds().contains(dependency)
            || isPackageProhibited(entry.getValue(), MODULES.get(dependency).basePackage())) {
          throw new IllegalStateException(entry.getKey() + " 同时允许和禁止依赖 " + dependency);
        }
      }
      for (String prohibitedModuleId : entry.getValue().prohibitedModuleIds()) {
        if (!MODULES.containsKey(prohibitedModuleId)) {
          throw new IllegalStateException(entry.getKey() + " 禁止项引用未登记模块 " + prohibitedModuleId);
        }
      }
    }
  }

  private static void visit(String moduleId, Set<String> visited, Set<String> visiting) {
    if (visited.contains(moduleId)) {
      return;
    }
    if (!visiting.add(moduleId)) {
      throw new AssertionError("模块允许依赖图存在循环，回到 " + moduleId);
    }
    for (String dependency : MODULES.get(moduleId).allowedDependencies()) {
      visit(dependency, visited, visiting);
    }
    visiting.remove(moduleId);
    visited.add(moduleId);
  }

  private record ModuleBoundary(
      String ownerId,
      String role,
      String basePackage,
      Set<String> allowedDependencies,
      Set<String> exposedPackages,
      Set<String> prohibitedModuleIds,
      Set<String> prohibitedPackages) {}
}
