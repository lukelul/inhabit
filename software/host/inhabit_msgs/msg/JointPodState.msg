std_msgs/Header header     # header.stamp = monotonic host RX time (the time-sync anchor)
uint8   node_id
uint8   chain_index
uint16  angle_raw_adc
int16   angle_millideg
float32 angle_rad          # derived convenience for consumers
uint8   status_flags
bool    checksum_valid      # from codec State.valid
uint32  schema_version      # = PROTO_VERSION (1)
