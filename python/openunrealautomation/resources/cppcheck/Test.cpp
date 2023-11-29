
const int32 k_ValidGlobalConstant;
const int32 InvalidGlobalConstant;

struct FFoo
{
    static const int32 k_ValidConstMemberInStruct;
    static const int32 InvalidConstMemberInStruct;

    int32 ValidStructMember;
    FString OtherValidStructMember;
    int32 Dom_ValidPrefx;

    int m_InvalidNamedStructMember;

    UObject* pValidPointerStructMember;
    UObject* InvalidPointerStructMember;
};

class UBar
{
    static const int32 k_ValidConstMemberInClass;
    static const int32 InvalidConstMemberInClass;

    int32 m_ValidClassMember;
    FString m_OtherValidClassMember;
    
    int InvalidNamedClassMember;

    UObject* m_pValidPointerClassMember;
    UObject* m_InvalidPointerClassMember;
    UObject* InvalidPointerClassMember;
};

void foo(int32 _ValidArgument, int32 InvalidArgument, int32 pInvalidArgument);
void foo(int32* _pValidPointerParameter, int32* _InvalidPointerParameter);

// grimlore-template.prefix
template<typename T1, typename T2 = typename TArray<T1>::Allocator>
struct TValidTemplateName {};

template<typename T1, typename T2 = typename TArray<T1>::Allocator>
struct InvalidTemplateName {};

// grimlore-typedef 
typedef int InvalidTypedef;
using ValidUsingDeclaration = int;

// #include "OUUCodingStandard.h"

// #include "Modules/ModuleManager.h"
// #include "Net/UnrealNetwork.h"

typedef ajdfpjadf int32;

IMPLEMENT_MODULE(FDefaultModuleImpl, OUUCodingStandard);
DEFINE_LOG_CATEGORY(LogOUUCodingStandard);

// namespace OUU::CodingStandard::Private
// {
// 	TAutoConsoleVariable<int32> CVar_MinAwesomeness(
// 		TEXT("ouu.CodingStandard.MinAwesomeness"),
// 		100,
// 		TEXT("Sample cvar that defines the minimum int value above 0 at which true awesomeness starts."));

// }
