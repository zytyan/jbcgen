#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include "json_pull.h"

typedef int32_t i32;

/// @jsonStruct
typedef struct City {
  i32 id;
  char name[32]; /// @json(omitempty)
} City;
struct Data {
  i32 accessCnt;
  int64_t lastAccess;
};
/// @jsonStruct
typedef struct User {
  /// @json(key=id, altkey=user-id, required)
  uint32_t id;
  /**
   * @json(key=name,
   *    maxlen=100,
   *    )
   */
  char *name;
  ///
  /// @json(
  ///      min=18,max=200,required
  /// )
  ///
  uint8_t age;
  /// @json(type=array, len=basesLen, required)
  City *bases;
  size_t basesLen;
  /// @json(flatten)
  struct Data data;
  /// @json(required)
  struct Data metadata;
} User;

#ifdef __cplusplus
extern "C" {
#endif

/// @jsonDecode
bool decodeUser(json_parser *parser, User *user);

/// @jsonCleanup
void releaseUser(json_allocator *allocator, User *user);

#ifdef __cplusplus
}
#endif
