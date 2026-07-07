.PHONY: test clean

CC ?= cc

test:
	$(CC) -I../inc -Wall -Wextra test_can_frame.c ../src/can_frame.c -o run_test && ./run_test
	$(CC) -I../inc -Wall -Wextra test_calib.c ../src/calib.c -o run_test_calib && ./run_test_calib
	$(CC) -I../inc -I../drivers -Wall -Wextra test_mcp2515.c ../drivers/mcp2515.c ../src/can_frame.c -o run_test_mcp2515 && ./run_test_mcp2515
	$(CC) -I../inc -I../drivers -Wall -Wextra test_can_health.c ../src/can_health.c ../src/can_frame.c -o run_test_can_health && ./run_test_can_health
	$(CC) -I../inc -Wall -Wextra test_enum.c ../src/enum.c ../src/can_frame.c -o run_test_enum && ./run_test_enum
	$(CC) -I../inc -Wall -Wextra test_enum_integrate.c ../src/enum.c ../src/can_frame.c -o run_test_enum_integrate && ./run_test_enum_integrate
	$(CC) -I../inc -Wall -Wextra test_bench_3pod.c ../src/enum.c ../src/can_frame.c -o run_test_bench3 && ./run_test_bench3
	$(CC) -Wall -Wextra -std=c11 -I../inc -c ../src/main.c -o run_main.o && rm -f run_main.o
clean:
	rm -f run_test run_test_calib run_test_mcp2515 run_test_can_health run_test_enum run_test_enum_integrate run_test_bench3 run_main.o
