#import <Foundation/Foundation.h>
#import <MapKit/MapKit.h>

static MKMapItem *geocode(NSString *address) {
    __block MKMapItem *item = nil;
    __block BOOL finished = NO;
    MKGeocodingRequest *request = [[MKGeocodingRequest alloc] initWithAddressString:address];
    [request getMapItemsWithCompletionHandler:^(NSArray<MKMapItem *> *items, NSError *error) {
        if (!error && items.firstObject) {
            item = items.firstObject;
        } else if (error) {
            fprintf(stderr, "Geocoding unavailable: %s\n", error.localizedDescription.UTF8String);
        }
        finished = YES;
    }];
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:20];
    while (!finished && deadline.timeIntervalSinceNow > 0) {
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
    }
    return item;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        MKMapItem *origin = geocode([NSString stringWithUTF8String:argv[1]]);
        MKMapItem *destination = geocode([NSString stringWithUTF8String:argv[2]]);
        if (!origin || !destination) return 1;

        MKDirectionsRequest *request = [[MKDirectionsRequest alloc] init];
        request.source = origin;
        request.destination = destination;
        request.transportType = MKDirectionsTransportTypeAutomobile;
        __block MKETAResponse *eta = nil;
        __block BOOL finished = NO;
        [[[MKDirections alloc] initWithRequest:request] calculateETAWithCompletionHandler:^(MKETAResponse *response, NSError *error) {
            if (!error) eta = response;
            else fprintf(stderr, "Traffic routing unavailable: %s\n", error.localizedDescription.UTF8String);
            finished = YES;
        }];
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:30];
        while (!finished && deadline.timeIntervalSinceNow > 0) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }
        if (!eta) return 1;

        NSDictionary *result = @{
            @"duration_seconds": @((NSInteger)llround(eta.expectedTravelTime)),
            @"distance_meters": @((NSInteger)llround(eta.distance))
        };
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        puts([[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] UTF8String]);
        return 0;
    }
}
