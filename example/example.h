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

/// @jsonStruct(asarray, elems=elems, len=len, cap=cap)
typedef struct {
  i32 *elems;
  size_t len;
  size_t cap;
  uint32_t reserved;
} IntVec;

/// @jsonStruct(asarray, elems=elems, len=len)
typedef struct NarrowIntVec {
  i32 *elems;
  uint8_t len;
} NarrowIntVec;

/// @jsonStruct(asarray, elems=elems, cap=cap)
typedef struct StringSlots {
  char **elems;
  size_t cap;
} StringSlots;

/// @jsonStruct(asarray, elems=elems)
typedef struct BareIntVec {
  i32 *elems;
} BareIntVec;

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

/// @jsonStruct
typedef struct VecEnvelope {
  IntVec *optional;
  /// @json(required)
  IntVec *required;
} VecEnvelope;

#ifdef __cplusplus
extern "C" {
#endif

/// @jsonDecode
bool decodeUser(json_parser *parser, User *user);

/// @jsonCleanup
void releaseUser(json_allocator *allocator, User *user);

/// @jsonDecode
bool decodeIntVec(json_parser *parser, IntVec *value);
/// @jsonCleanup
void releaseIntVec(json_allocator *allocator, IntVec *value);

/// @jsonDecode
bool decodeNarrowIntVec(json_parser *parser, NarrowIntVec *value);
/// @jsonCleanup
void releaseNarrowIntVec(json_allocator *allocator, NarrowIntVec *value);

/// @jsonDecode
bool decodeStringSlots(json_parser *parser, StringSlots *value);
/// @jsonCleanup
void releaseStringSlots(json_allocator *allocator, StringSlots *value);

/// @jsonDecode
bool decodeBareIntVec(json_parser *parser, BareIntVec *value);
/// @jsonCleanup
void releaseBareIntVec(json_allocator *allocator, BareIntVec *value);

/// @jsonDecode
bool decodeVecEnvelope(json_parser *parser, VecEnvelope *value);
/// @jsonCleanup
void releaseVecEnvelope(json_allocator *allocator, VecEnvelope *value);

#ifdef __cplusplus
}
#endif
