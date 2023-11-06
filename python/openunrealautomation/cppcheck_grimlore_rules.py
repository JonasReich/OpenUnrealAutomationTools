"""
Check for unique Grimlore code style rules.
These are supplemental to what ReSharper InspectCode detects out of the box.
Especially naming rules focus on the differences to standard UE naming conventions.
"""

import cppcheckdata
import sys
import re


def reportError(token, severity, msg, errorId):
    cppcheckdata.reportError(token, severity, msg, "grim", errorId)


def reportNamingError(token, nametoken, msg, errorId):
    reportError(token, "style",
                msg=f"{nametoken}: {msg}", errorId=f"naming-{errorId}")


def get_args():
    parser = cppcheckdata.ArgumentParser()
    return parser.parse_args()


if __name__ == '__main__':
    args = get_args()

    for dumpfile in args.dumpfile:
        if "AJFADJFP" in str(dumpfile):
            continue
            reportError(cppcheckdata.Location(), "error", "You ran the grimlore coding rules on OpenUnreal code, which doesn't follow the Grimlore code style!", "openunreal.exception")

        data = cppcheckdata.CppcheckData(dumpfile)

        for cfg in data.iterconfigurations():
            # if False:
            #     for scope in cfg.scopes:
            #         if scope.type == 'Function':
            #             function = scope.function
            #             if function is not None and function.type in ('Constructor', 'Destructor', 'CopyConstructor', 'MoveConstructor'):
            #                 continue
            #             res = re.match(RE_FUNCTIONNAME, scope.className)
            #             if not res:
            #                 reportError(
            #                     scope.bodyStart, 'style', 'Function ' + scope.className + ' violates naming convention', 'functionName')

            # for scope in cfg.scopes:
            #     scope:cppcheckdata.Scope
            #     if scope.type in ["Struct", "Class"]:
            #         if scope.bodyStart

            for typedef in cfg.typedefInfo:
                typedef : cppcheckdata.TypedefInfo
                reportError(typedef, "error", "Use modern using declaration instead of typedef", "grim-typedef")
                pass

            for token in cfg.tokenlist:
                token: cppcheckdata.Token
                if token.str == "template":
                    template_bracket_start:cppcheckdata.Token = token.next
                    if template_bracket_start is None:
                        continue
                    template_bracket_end:cppcheckdata.Token = template_bracket_start.link
                    if template_bracket_end is None:
                        continue
                    template_struct_or_class:cppcheckdata.Token = template_bracket_end.next
                    if template_struct_or_class is None or template_struct_or_class.str not in ["struct", "class"]:
                        continue
                    template_name_token:cppcheckdata.Token = template_struct_or_class.next
                    if template_name_token is None:
                        continue
                    template_name = str(template_name_token.str)
                    if not template_name.startswith("T"):
                        reportNamingError(template_name_token, template_name,
                                          "Missing T prefix for templates", "template.prefix")

            for var in cfg.variables:
                var: cppcheckdata.Variable

                var_name = str(var.nameToken.str)

                if var.isPointer:
                    has_p_prefix = re.match("^(m?_)?p.+$",var_name)
                    if not has_p_prefix:
                        reportNamingError(var.typeStartToken, var_name,
                                          "Missing p prefix for pointer variables.", "pointer.prefix")

                if var.isArgument:
                    if not var_name.startswith("_"):
                        reportNamingError(var.typeStartToken, var_name,
                                          "Missing _ prefix for function parameters.", "parameter.prefix")

                if var.access in ["Global", "Namespace"]:
                    if var.isConst and not re.match("^k_.+$", var_name):
                        reportNamingError(var.typeStartToken, var_name,
                                          "Missing k_ prefix for static and global constants.", "constant.prefix")

                if var.access in ["Public", "Protected", "Private"]:
                    has_m_prefix = var_name.startswith("m_")
                    has_k_prefix = var_name.startswith("k_")
                    is_class = var.scope.type == "Class"
                    if var.isConst and var.isStatic:
                        if not has_k_prefix:
                            reportNamingError(var.typeStartToken, var_name,
                                              "Missing k_ prefix for static and global constants.", "constant.prefix")
                    elif has_m_prefix and not is_class:
                        reportNamingError(var.typeStartToken, var_name,
                                          "Bad m_ prefix for struct members. Only use it for class members.", "struct.member.prefix")
                    elif not has_m_prefix and is_class:
                        reportNamingError(var.typeStartToken, var_name,
                                          "Missing m_ prefix for class members.", "class.member.prefix")

    sys.exit(cppcheckdata.EXIT_CODE)
