#include <stdint.h>
#include <stddef.h>

typedef int32_t i32;

/// @jsonStruct
typedef struct City {
  i32 id;
  char name[32]; /// @json(omitempty)
} City;

/// @jsonStruct
typedef struct User {
  /// @json(key=id, altkey=user-id)
  uint32_t id; /// @json
  /**
   * @json(key=name,
   * maxlen=100)
   */
  char *name;
  //
  // @json(
  //      min=18
  // )
  //
  uint8_t age;
  /// @json(type=array, lenfield=lasesLen)
  City *bases;
  size_t basesLen;
} User;